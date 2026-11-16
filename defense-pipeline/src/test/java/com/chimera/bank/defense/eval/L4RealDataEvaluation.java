package com.chimera.bank.defense.eval;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.ai.SeverityAdvisor;
import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.detect.OnnxSemanticInjectionGuard;
import com.chimera.bank.defense.layers.L4_InjectionLeakLayer;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Offline evaluation of the deterministic L4 injection/leak detector against a real labeled split
 * produced by {@code chimera_datasets build}. Skipped in normal builds; run explicitly with:
 *
 * <pre>
 * mvn -pl defense-pipeline -am test -Dtest=L4RealDataEvaluation -DfailIfNoTests=false \
 *     -Dchimera.eval.input=out/eval_input.jsonl -Dchimera.eval.output=out/l4_predictions.csv
 * </pre>
 *
 * <p>Input is JSONL ({@code id,payload,label}); output is {@code id,pred} CSV where pred is the L4
 * decision (PASS / CHALLENGE / QUARANTINE / BLOCK). Score it with {@code chimera_datasets score}.
 * By default this uses the offline L4 constructor (deterministic scanner + canaries, no ONNX
 * semantic guard and no AI-brain severity refinement), so the number reflects the rule-based
 * baseline only.
 *
 * <p>To evaluate a trained ONNX semantic guard on top of the deterministic detectors, also set
 * {@code -Dchimera.eval.semantic.model=<model.int8.onnx>} and
 * {@code -Dchimera.eval.semantic.vocab=<vocab.txt>}. The semantic timeout defaults to 1000 ms
 * ({@code -Dchimera.eval.semantic.timeout-ms}) — the guard's maximum allowed bound — so recall
 * measures model skill rather than fail-closed timeouts; per-row latency percentiles are printed
 * to judge the deployment budget.
 */
class L4RealDataEvaluation {

    @Test
    void evaluateDeterministicL4() throws Exception {
        String input = System.getProperty("chimera.eval.input");
        String output = System.getProperty("chimera.eval.output");
        Assumptions.assumeTrue(input != null && output != null,
                "set -Dchimera.eval.input and -Dchimera.eval.output to run the real-data evaluation");

        ObjectMapper mapper = new ObjectMapper();
        String semanticModel = System.getProperty("chimera.eval.semantic.model");
        String semanticVocab = System.getProperty("chimera.eval.semantic.vocab");
        long semanticTimeoutMs = Long.getLong("chimera.eval.semantic.timeout-ms", 1000L);
        double semanticThreshold = Double.parseDouble(
                System.getProperty("chimera.eval.semantic.threshold", "0.65"));
        OnnxSemanticInjectionGuard guard = null;
        L4_InjectionLeakLayer l4;
        if (semanticModel != null && semanticVocab != null) {
            guard = new OnnxSemanticInjectionGuard(semanticModel, semanticVocab, 128, 8192,
                    semanticTimeoutMs, semanticThreshold);
            var st = guard.status();
            System.out.printf("[L4 eval] guard configured=%s available=%s detail=%s%n",
                    st.configured(), st.available(), st.detail());
            l4 = new L4_InjectionLeakLayer(new CanaryTokenRegistry(), SeverityAdvisor.LOCAL_ONLY, guard);
        } else {
            l4 = new L4_InjectionLeakLayer(new CanaryTokenRegistry());
        }
        List<String> lines = Files.readAllLines(Path.of(input), StandardCharsets.UTF_8);
        List<String> decisions = new ArrayList<>();

        int tp = 0, fp = 0, tn = 0, fn = 0, rows = 0;
        List<Long> latencies = new ArrayList<>();
        List<Long> replayLatencies = new ArrayList<>();
        int replayMismatches = 0;
        long start = System.nanoTime();
        try (BufferedWriter w = Files.newBufferedWriter(Path.of(output), StandardCharsets.UTF_8)) {
            w.write("id,pred\n");
            for (String line : lines) {
                if (line.isBlank()) continue;
                JsonNode node = mapper.readTree(line);
                String id = node.get("id").asText();
                String payload = node.get("payload").asText();
                int label = node.get("label").asInt();
                DefenseContext ctx = new DefenseContext("eval-" + id, Instant.now(), "192.168.1.9",
                        "REG-EVAL", Role.CUSTOMER, "transfer", payload);
                long rowStart = System.nanoTime();
                LayerVerdict verdict = l4.inspect(ctx);
                latencies.add((System.nanoTime() - rowStart) / 1_000_000);
                String pred = verdict.decision().name();
                decisions.add(pred);
                w.write(id + "," + pred + "\n");
                boolean detected = verdict.decision() != LayerVerdict.Decision.PASS;
                if (label == 1 && detected) tp++;
                else if (label == 1) fn++;
                else if (detected) fp++;
                else tn++;
                rows++;
            }
            long elapsedMs = (System.nanoTime() - start) / 1_000_000;
            double recall = tp + fn == 0 ? 0 : (double) tp / (tp + fn);
            double fpr = fp + tn == 0 ? 0 : (double) fp / (fp + tn);
            Collections.sort(latencies);
            System.out.printf("[L4 eval] mode=%s rows=%d TP=%d FP=%d TN=%d FN=%d recall=%.4f fpr=%.4f "
                            + "elapsedMs=%d latencyMs p50=%d p95=%d max=%d%n",
                    guard == null ? "deterministic" : "onnx", rows, tp, fp, tn, fn, recall, fpr,
                    elapsedMs, percentile(latencies, 0.50), percentile(latencies, 0.95),
                    latencies.isEmpty() ? 0 : latencies.get(latencies.size() - 1));

            // Second pass over identical payloads measures the verdict cache (repeat/replay traffic).
            if (guard != null && Boolean.getBoolean("chimera.eval.replay")) {
                int index = 0;
                long replayStartNs = System.nanoTime();
                for (String line : lines) {
                    if (line.isBlank()) continue;
                    JsonNode node = mapper.readTree(line);
                    DefenseContext ctx = new DefenseContext("replay-" + node.get("id").asText(), Instant.now(),
                            "192.168.1.9", "REG-EVAL", Role.CUSTOMER, "transfer", node.get("payload").asText());
                    long rowStartNs = System.nanoTime();
                    String pred = l4.inspect(ctx).decision().name();
                    replayLatencies.add((System.nanoTime() - rowStartNs) / 1_000);
                    if (!pred.equals(decisions.get(index++))) replayMismatches++;
                }
                long replayElapsedMs = (System.nanoTime() - replayStartNs) / 1_000_000;
                Collections.sort(replayLatencies);
                System.out.printf("[L4 eval] replay rows=%d decisionMismatches=%d elapsedMs=%d latencyUs p50=%d "
                                + "p95=%d max=%d cache=%s%n",
                        replayLatencies.size(), replayMismatches, replayElapsedMs,
                        percentile(replayLatencies, 0.50), percentile(replayLatencies, 0.95),
                        replayLatencies.get(replayLatencies.size() - 1), guard.cacheStats());
            }
        } finally {
            if (guard != null) guard.close();
        }
    }

    private static long percentile(List<Long> sorted, double q) {
        if (sorted.isEmpty()) return 0;
        int index = (int) Math.ceil(q * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(index, sorted.size() - 1)));
    }
}