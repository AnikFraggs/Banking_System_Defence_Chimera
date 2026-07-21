package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import com.chimera.bank.defense.ai.SeverityAdvisor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * Layer 5: AI-vs-human verification.
 *
 * <p>Uses a defensive "ghost-text" challenge: the client is issued a prompt that
 * contains an instruction rendered invisibly / out-of-band to a human (via the
 * UI), such that a legitimate human client returns the expected human response,
 * while an automated agent that naively ingests the raw text follows the decoy
 * instruction and is revealed. This is an anti-automation tripwire on the bank's
 * OWN login/transaction flow — not an attack on any external system.
 *
 * <p>The signal {@code human_challenge_passed} is set by the front-end challenge
 * exchange (handled in platform-api). Here we only enforce it for elevated risk.
 */
@Component
public class L5_HumanVerificationLayer implements DefenseLayer {

    private final SeverityAdvisor advisor;

    /** Test / offline constructor: local severity only. */
    public L5_HumanVerificationLayer() {
        this(SeverityAdvisor.LOCAL_ONLY);
    }

    @Autowired
    public L5_HumanVerificationLayer(ObjectProvider<SeverityAdvisor> advisor) {
        this(advisor.getIfAvailable(() -> SeverityAdvisor.LOCAL_ONLY));
    }

    public L5_HumanVerificationLayer(SeverityAdvisor advisor) {
        this.advisor = advisor;
    }

    @Override
    public int order() {
        return 5;
    }

    @Override
    public String name() {
        return "L5_human_verification";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        Object passed = ctx.signals().get("human_challenge_passed");
        boolean humanVerified = Boolean.TRUE.equals(passed);
        boolean priorSuspicion = Boolean.TRUE.equals(ctx.signals().get("injection_phrasing"))
                || Boolean.TRUE.equals(ctx.signals().get("invisible_chars"))
                || Boolean.TRUE.equals(ctx.signals().get("homoglyph_evasion"))
                || Boolean.TRUE.equals(ctx.signals().get("nested_encoding"));

        ctx.addSignal("human_verified", humanVerified);

        if (humanVerified) {
            return LayerVerdict.pass(name());
        }
        // Not yet verified: require the ghost-text challenge. Escalate severity if
        // earlier layers already saw automation-like content.
        double localSeverity = priorSuspicion ? 0.7 : 0.4;
        Map<String, Object> telemetry = Map.of(
                "human_challenge_passed", false,
                "prior_suspicion", priorSuspicion,
                "behavior_anomaly", localSeverity);
        SeverityAdvisor.Advice advice = advisor.refine(ctx, name(), localSeverity, telemetry);
        double severity = Math.max(localSeverity, advice.severity());
        ctx.addSignal("l5_local_severity", localSeverity);
        ctx.addSignal("l5_brain_risk", advice.brainRiskScore());
        ctx.addSignal("l5_brain_fallback", advice.fromFallback());
        return LayerVerdict.challenge(name(), "ghost_text_human_challenge_required", severity);
    }
}
