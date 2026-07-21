package com.chimera.bank.defense.validation;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.defense.DefenseOrchestrator;
import com.chimera.bank.defense.DefenseOrchestrator.Disposition;
import com.chimera.bank.defense.DefenseOrchestrator.OrchestrationOutcome;
import com.chimera.bank.defense.metrics.Metrics;
import com.chimera.bank.defense.redteam.AdversarialSample;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Runs a labeled battery through the full defense flow ({@link DefenseOrchestrator})
 * and computes the report the operator asked for:
 *
 * <ul>
 *   <li><b>Per-layer health %</b> — recall + precision + severity calibration
 *       (RMSE, Pearson r) for the samples each layer is responsible for halting.</li>
 *   <li><b>Overall calibration</b> — Pearson r and RMSE of predicted vs ground-truth
 *       severity across the whole battery.</li>
 *   <li><b>RAG recovery rate</b> — of the sessions that triggered self-healing,
 *       the fraction the RAG playbooks remediated (REMEDIATED) vs those that had
 *       to be relocated to the vault (VAULTED). This is the measured form of the
 *       "heal the compromised layer" step in the loop.</li>
 * </ul>
 *
 * <p>The loop for each sample is exactly: <em>face the attacker → run every ring
 * (prevent) → on a raised threat, RAG self-heal the compromised layer → if heal
 * fails, contain in the vault → record the outcome for the report.</em>
 */
public final class ValidationHarness {

    private final DefenseOrchestrator orchestrator;

    public ValidationHarness(DefenseOrchestrator orchestrator) {
        this.orchestrator = orchestrator;
    }

    public record LayerHealth(
            String layer, int samples, int truePos, int falseNeg, int falsePos,
            double recall, double precision, double rmse, double pearsonR, double healthPercent) {
    }

    public record RecoveryReport(
            int healingTriggered, int remediated, int vaulted, int blocked,
            double recoveryRatePercent) {
    }

    public record ValidationReport(
            int total, int malicious, int benign,
            int truePos, int trueNeg, int falsePos, int falseNeg,
            double accuracy, double precision, double recall, double f1,
            double pearsonR, double rmse,
            Map<String, LayerHealth> perLayerHealth,
            RecoveryReport recovery) {
    }

    public ValidationReport run(List<AdversarialSample> battery) {
        List<Double> predicted = new ArrayList<>();
        List<Double> actual = new ArrayList<>();
        int tp = 0, tn = 0, fp = 0, fn = 0;

        // Recovery accounting.
        int healingTriggered = 0, remediated = 0, vaulted = 0, blocked = 0;

        // Per-layer accumulation keyed by the layer that HALTED the request (for
        // malicious) or the sample's target layer (for false negatives / benign).
        Map<String, List<double[]>> perLayerPredActual = new TreeMap<>();
        Map<String, int[]> perLayerConfusion = new TreeMap<>(); // [tp, fn, fp]

        for (AdversarialSample s : battery) {
            DefenseContext ctx = toContext(s);
            OrchestrationOutcome out = orchestrator.handle(ctx);

            boolean flagged = out.disposition() != Disposition.ALLOWED;
            double predSeverity = out.triggeringVerdict().severity();
            String haltLayer = out.triggeringVerdict().layer();

            predicted.add(predSeverity);
            actual.add(s.expectedSeverity());

            if (s.malicious() && flagged) tp++;
            else if (s.malicious()) fn++;
            else if (flagged) fp++;
            else tn++;

            // Recovery loop accounting.
            switch (out.disposition()) {
                case REMEDIATED -> { healingTriggered++; remediated++; }
                case VAULTED -> { healingTriggered++; vaulted++; }
                case BLOCKED -> blocked++;
                case ALLOWED -> { /* no threat raised */ }
            }

            // Attribute to a layer: where it actually halted if flagged, else its
            // intended target layer (so a miss counts against the right ring).
            String layer = flagged ? haltLayer : s.targetLayer();
            perLayerPredActual.computeIfAbsent(layer, k -> new ArrayList<>())
                    .add(new double[]{predSeverity, s.expectedSeverity()});
            int[] conf = perLayerConfusion.computeIfAbsent(layer, k -> new int[3]);
            if (s.malicious() && flagged) conf[0]++;
            else if (s.malicious()) conf[1]++;
            else if (flagged) conf[2]++;
        }

        int n = battery.size();
        int malicious = tp + fn;
        int benign = tn + fp;
        double precision = Metrics.precision(tp, fp);
        double recall = Metrics.recall(tp, fn);
        double f1 = Metrics.f1(precision, recall);
        double accuracy = n == 0 ? 0 : (double) (tp + tn) / n;

        double[] p = toArray(predicted);
        double[] a = toArray(actual);
        double r = safePearson(p, a);
        double rmse = Metrics.rmse(p, a);

        Map<String, LayerHealth> perLayer = buildPerLayerHealth(perLayerPredActual, perLayerConfusion);

        double recoveryRate = healingTriggered == 0 ? 100.0
                : Math.round((double) remediated / healingTriggered * 1000.0) / 10.0;
        RecoveryReport recovery = new RecoveryReport(
                healingTriggered, remediated, vaulted, blocked, recoveryRate);

        return new ValidationReport(
                n, malicious, benign, tp, tn, fp, fn,
                Metrics.round4(accuracy), Metrics.round4(precision),
                Metrics.round4(recall), Metrics.round4(f1),
                Metrics.round4(r), Metrics.round4(rmse),
                perLayer, recovery);
    }

    private Map<String, LayerHealth> buildPerLayerHealth(
            Map<String, List<double[]>> perLayerPredActual, Map<String, int[]> perLayerConfusion) {

        Map<String, LayerHealth> perLayer = new LinkedHashMap<>();
        for (var e : perLayerPredActual.entrySet()) {
            String layer = e.getKey();
            List<double[]> pairs = e.getValue();
            double[] lp = new double[pairs.size()];
            double[] la = new double[pairs.size()];
            for (int i = 0; i < pairs.size(); i++) {
                lp[i] = pairs.get(i)[0];
                la[i] = pairs.get(i)[1];
            }
            int[] conf = perLayerConfusion.getOrDefault(layer, new int[3]);
            int ltp = conf[0], lfn = conf[1], lfp = conf[2];
            double lrecall = Metrics.recall(ltp, lfn);
            double lprecision = Metrics.precision(ltp, lfp);
            double lrmse = Metrics.rmse(lp, la);
            double lr = safePearson(lp, la);
            double health = Metrics.healthPercent(lrecall, lprecision, lrmse, lr);
            perLayer.put(layer, new LayerHealth(
                    layer, pairs.size(), ltp, lfn, lfp,
                    Metrics.round4(lrecall), Metrics.round4(lprecision),
                    Metrics.round4(lrmse), Metrics.round4(lr), health));
        }
        return perLayer;
    }

    /** Pearson is undefined when either series has zero variance; treat as 0 there. */
    private static double safePearson(double[] x, double[] y) {
        if (x.length < 2) {
            return 0.0;
        }
        try {
            return Metrics.pearson(x, y);
        } catch (IllegalArgumentException e) {
            return 0.0;
        }
    }

    private static double[] toArray(List<Double> list) {
        double[] out = new double[list.size()];
        for (int i = 0; i < list.size(); i++) {
            out[i] = list.get(i);
        }
        return out;
    }

    private static DefenseContext toContext(AdversarialSample s) {
        DefenseContext c = new DefenseContext(
                "cor-" + s.id(), java.time.Instant.now(), s.sourceIp(),
                s.role() == null ? "UNKNOWN" : "REG-" + s.role().name(),
                s.role(), s.purpose(), s.payload());
        if (s.humanVerified()) {
            c.addSignal("human_challenge_passed", true);
        }
        return c;
    }

    /** Human-readable report block for logs / console. */
    public static String format(ValidationReport rep) {
        StringBuilder b = new StringBuilder();
        b.append("\n============= DEFENSE VALIDATION REPORT =============\n");
        b.append(String.format("samples=%d  malicious=%d  benign=%d%n",
                rep.total(), rep.malicious(), rep.benign()));
        b.append(String.format("Confusion  TP=%d TN=%d FP=%d FN=%d%n",
                rep.truePos(), rep.trueNeg(), rep.falsePos(), rep.falseNeg()));
        b.append(String.format("Accuracy=%.4f Precision=%.4f Recall=%.4f F1=%.4f%n",
                rep.accuracy(), rep.precision(), rep.recall(), rep.f1()));
        b.append(String.format("Severity calibration: Pearson r=%.4f  RMSE=%.4f%n",
                rep.pearsonR(), rep.rmse()));
        b.append("----------------- per-layer health -----------------\n");
        b.append(String.format("%-22s %6s %8s %9s %7s %7s %8s%n",
                "layer", "n", "recall", "precision", "rmse", "r", "health%"));
        for (LayerHealth h : rep.perLayerHealth().values()) {
            b.append(String.format("%-22s %6d %8.3f %9.3f %7.3f %7.3f %7.1f%%%n",
                    h.layer(), h.samples(), h.recall(), h.precision(),
                    h.rmse(), h.pearsonR(), h.healthPercent()));
        }
        RecoveryReport rc = rep.recovery();
        b.append("----------------- RAG recovery ---------------------\n");
        b.append(String.format("healing_triggered=%d  remediated=%d  vaulted=%d  hard_blocked=%d%n",
                rc.healingTriggered(), rc.remediated(), rc.vaulted(), rc.blocked()));
        b.append(String.format("RAG recovery rate = %.1f%%  (remediated / healing_triggered)%n",
                rc.recoveryRatePercent()));
        b.append("====================================================\n");
        return b.toString();
    }
}
