package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import com.chimera.bank.defense.ai.SeverityAdvisor;
import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.detect.InjectionScanner;
import com.chimera.bank.defense.detect.SemanticInjectionGuard;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * Layer 4: data-leak and prompt-injection defense.
 *
 * <p>Scans the request payload for invisible-Unicode / zero-width steganography,
 * bidi "Trojan Source" controls, and prompt-injection phrasing before any inner
 * LLM layer ever sees the text. It also checks for tripped {@link
 * CanaryTokenRegistry} tokens, which indicate leaked internal context.
 *
 * <ul>
 *   <li>A tripped canary is a hard QUARANTINE (protected context has leaked).</li>
 *   <li>High-severity injection/stego is a BLOCK.</li>
 *   <li>Lower-severity findings become a CHALLENGE, and the layer stores the
 *       <em>sanitized</em> text so downstream LLM layers never process the
 *       hidden characters.</li>
 * </ul>
 */
@Component
public class L4_InjectionLeakLayer implements DefenseLayer {

    /**
     * The semantic classifier is trained on sentence-length instruction text. A
     * one- or two-word transaction reference ("refund", "ATM withdrawal") has no
     * instruction structure and is out of distribution; measured on this model
     * it produced false-positive CHALLENGEs on ordinary banking vocabulary.
     * Deterministic regex/stego scanning still runs on every payload (and catches
     * short explicit injections such as "ignore previous instructions"), so the
     * model is only consulted once the text is long enough to carry an
     * instruction.
     */
    private static final int SEMANTIC_MIN_TOKENS = 3;

    private final InjectionScanner scanner = new InjectionScanner();
    private final CanaryTokenRegistry canaries;
    private final SeverityAdvisor advisor;
    private final SemanticInjectionGuard semanticGuard;

    /** Test / offline constructor: deterministic baseline only. */
    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries) {
        this(canaries, SeverityAdvisor.LOCAL_ONLY, SemanticInjectionGuard.disabled());
    }

    /** Spring constructor: the semantic guard is a singleton and is never built per request. */
    @Autowired
    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries, ObjectProvider<SeverityAdvisor> advisor,
                                 ObjectProvider<SemanticInjectionGuard> semanticGuard) {
        this(canaries, advisor.getIfAvailable(() -> SeverityAdvisor.LOCAL_ONLY),
                semanticGuard.getIfAvailable(SemanticInjectionGuard::disabled));
    }

    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries, SeverityAdvisor advisor) {
        this(canaries, advisor, SemanticInjectionGuard.disabled());
    }

    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries, SeverityAdvisor advisor,
                                 SemanticInjectionGuard semanticGuard) {
        this.canaries = canaries;
        this.advisor = advisor;
        this.semanticGuard = semanticGuard;
    }

    @Override
    public int order() {
        return 4;
    }

    @Override
    public String name() {
        return "L4_injection_leak";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        // Cheap status probe only — no inference. The costly ONNX assess() is
        // deferred until the deterministic primitives have had their say.
        SemanticInjectionGuard.Status semanticStatus = semanticGuard.status();
        ctx.addSignal("semantic_guard_configured", semanticStatus.configured());
        ctx.addSignal("semantic_guard_available", semanticStatus.available());
        ctx.addSignal("semantic_guard_status", semanticStatus.detail());

        // 1. Deterministic canary check first: a tripped canary is a hard
        //    QUARANTINE (protected context leaked). The semantic model can only
        //    escalate, so it is never needed here — skip ONNX inference entirely.
        String tripped = canaries.trip(ctx.payload());
        if (tripped != null) {
            ctx.addSignal("canary_tripped", true);
            ctx.addSignal("canary_token", tripped);
            ctx.addSignal("semantic_guard_skipped", true);
            ctx.addSignal("semantic_guard_score", 0.0);
            ctx.addSignal("semantic_guard_reason", "short_circuited:canary_quarantine");
            return LayerVerdict.quarantine(name(), "canary_token_present_context_leak", 0.98);
        }

        // 2. Deterministic injection/stego scan. Always hand the sanitized text
        //    forward so no inner layer sees hidden characters.
        InjectionScanner.ScanReport report = scanner.scan(ctx.payload());
        ctx.addSignal("invisible_chars", report.invisibleChars());
        ctx.addSignal("invisible_count", report.invisibleCount());
        ctx.addSignal("bidi_controls", report.bidiControls());
        ctx.addSignal("injection_phrasing", report.injectionPhrasing());
        ctx.addSignal("homoglyph_evasion", report.homoglyphEvasion());
        ctx.addSignal("nested_encoding", report.nestedEncoding());
        ctx.addSignal("encoding_depth", report.encodingDepth());
        ctx.addSignal("sanitized_payload", report.sanitized());
        double localSeverity = report.severity();

        // 3. The semantic guard is escalate-only: it can lift a clean PASS to a
        //    CHALLENGE (broad jailbreak class the rules miss) or a sub-BLOCK dirty
        //    CHALLENGE to a BLOCK. A deterministic hit already at BLOCK severity
        //    needs no model opinion, so short-circuit the ONNX inference there.
        boolean deterministicBlock = !report.clean() && localSeverity >= 0.7;
        SemanticInjectionGuard.Result semantic;
        if (deterministicBlock) {
            semantic = SemanticInjectionGuard.Result.pass();
            ctx.addSignal("semantic_guard_skipped", true);
            ctx.addSignal("semantic_guard_score", 0.0);
            ctx.addSignal("semantic_guard_reason", "short_circuited:deterministic_block");
        } else if (!hasInstructionStructure(ctx.payload())) {
            semantic = SemanticInjectionGuard.Result.pass();
            ctx.addSignal("semantic_guard_skipped", true);
            ctx.addSignal("semantic_guard_score", 0.0);
            ctx.addSignal("semantic_guard_reason", "short_circuited:payload_too_short_for_semantic_model");
        } else {
            semantic = semanticGuard.assess(ctx.payload());
            ctx.addSignal("semantic_guard_skipped", false);
            ctx.addSignal("semantic_guard_score", semantic.score());
            ctx.addSignal("semantic_guard_reason", semantic.reason());
        }

        if (report.clean()) {
            return semantic.challenge()
                    ? LayerVerdict.challenge(name(), semantic.reason(), Math.max(0.65, semantic.score()))
                    : LayerVerdict.pass(name());
        }

        // Dirty payload: local detector severity, refined by the AI brain. Both
        // the brain and the semantic guard can only ESCALATE — take the max so a
        // model false-negative can never downgrade a concrete detector hit, while
        // a model that recognizes a subtle attack can push a borderline CHALLENGE
        // up to a BLOCK. On a deterministic BLOCK the semantic term is 0 (skipped).
        double semanticSeverity = semantic.challenge() ? Math.max(semantic.score(), 0.0) : 0.0;
        Map<String, Object> telemetry = Map.of(
                "invisible_count", report.invisibleCount(),
                "bidi_controls", report.bidiControls(),
                "injection_phrasing", report.injectionPhrasing(),
                "homoglyph_evasion", report.homoglyphEvasion(),
                "nested_encoding", report.nestedEncoding(),
                "encoding_depth", report.encodingDepth(),
                "semantic_severity", semanticSeverity,
                "behavior_anomaly", localSeverity);
        SeverityAdvisor.Advice advice = advisor.refine(ctx, name(), localSeverity, telemetry);
        double severity = Math.max(localSeverity, Math.max(advice.severity(), semanticSeverity));
        ctx.addSignal("l4_local_severity", localSeverity);
        ctx.addSignal("l4_brain_risk", advice.brainRiskScore());
        ctx.addSignal("l4_brain_fallback", advice.fromFallback());

        if (severity >= 0.7 || advice.requiresHumanApproval() && severity >= 0.6) {
            return LayerVerdict.block(name(), "high_severity_injection_or_stego", severity);
        }
        return LayerVerdict.challenge(name(), "suspicious_content_sanitized", severity);
    }

    /** True when the payload is long enough to carry an instruction (>= 3 whitespace tokens). */
    private static boolean hasInstructionStructure(String payload) {
        if (payload == null || payload.isBlank()) {
            return false;
        }
        int tokens = 0;
        for (String part : payload.trim().split("\\s+")) {
            if (!part.isBlank() && ++tokens >= SEMANTIC_MIN_TOKENS) {
                return true;
            }
        }
        return false;
    }
}
