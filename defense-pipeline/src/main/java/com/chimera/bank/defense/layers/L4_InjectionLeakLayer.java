package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import com.chimera.bank.defense.ai.SeverityAdvisor;
import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.detect.InjectionScanner;
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

    private final InjectionScanner scanner = new InjectionScanner();
    private final CanaryTokenRegistry canaries;
    private final SeverityAdvisor advisor;

    /** Test / offline constructor: local severity only, no AI-brain refinement. */
    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries) {
        this(canaries, SeverityAdvisor.LOCAL_ONLY);
    }

    /** Spring constructor: refine severity via the AI brain when an advisor bean exists. */
    @Autowired
    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries, ObjectProvider<SeverityAdvisor> advisor) {
        this(canaries, advisor.getIfAvailable(() -> SeverityAdvisor.LOCAL_ONLY));
    }

    public L4_InjectionLeakLayer(CanaryTokenRegistry canaries, SeverityAdvisor advisor) {
        this.canaries = canaries;
        this.advisor = advisor;
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
        String tripped = canaries.trip(ctx.payload());
        if (tripped != null) {
            ctx.addSignal("canary_tripped", true);
            ctx.addSignal("canary_token", tripped);
            return LayerVerdict.quarantine(name(), "canary_token_present_context_leak", 0.98);
        }

        InjectionScanner.ScanReport report = scanner.scan(ctx.payload());
        ctx.addSignal("invisible_chars", report.invisibleChars());
        ctx.addSignal("invisible_count", report.invisibleCount());
        ctx.addSignal("bidi_controls", report.bidiControls());
        ctx.addSignal("injection_phrasing", report.injectionPhrasing());
        ctx.addSignal("homoglyph_evasion", report.homoglyphEvasion());
        ctx.addSignal("nested_encoding", report.nestedEncoding());
        ctx.addSignal("encoding_depth", report.encodingDepth());
        // Always hand the sanitized text forward so no inner layer sees hidden chars.
        ctx.addSignal("sanitized_payload", report.sanitized());

        if (report.clean()) {
            return LayerVerdict.pass(name());
        }

        // Local detector severity, then refined by the AI brain (XGBoost + RAG).
        // The brain can only ESCALATE here: we take the max of local and brain
        // severity so a model false-negative can never downgrade a concrete
        // detector hit, while a model that recognizes a subtle attack can push a
        // borderline CHALLENGE up to a BLOCK.
        double localSeverity = report.severity();
        Map<String, Object> telemetry = Map.of(
                "invisible_count", report.invisibleCount(),
                "bidi_controls", report.bidiControls(),
                "injection_phrasing", report.injectionPhrasing(),
                "homoglyph_evasion", report.homoglyphEvasion(),
                "nested_encoding", report.nestedEncoding(),
                "encoding_depth", report.encodingDepth(),
                "behavior_anomaly", localSeverity);
        SeverityAdvisor.Advice advice = advisor.refine(ctx, name(), localSeverity, telemetry);
        double severity = Math.max(localSeverity, advice.severity());
        ctx.addSignal("l4_local_severity", localSeverity);
        ctx.addSignal("l4_brain_risk", advice.brainRiskScore());
        ctx.addSignal("l4_brain_fallback", advice.fromFallback());

        if (severity >= 0.7 || advice.requiresHumanApproval() && severity >= 0.6) {
            return LayerVerdict.block(name(), "high_severity_injection_or_stego", severity);
        }
        return LayerVerdict.challenge(name(), "suspicious_content_sanitized", severity);
    }
}
