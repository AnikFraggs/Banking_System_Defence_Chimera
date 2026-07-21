package com.chimera.bank.ai;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.defense.ai.SeverityAdvisor;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * Production {@link SeverityAdvisor} that refines L4/L5 severity using the Python
 * "AI brain" via {@link AiBrainClient}. Registered as a Spring bean, it is picked
 * up automatically by the {@code ObjectProvider<SeverityAdvisor>} constructors in
 * the AI-security layers; if this module is absent, those layers fall back to
 * {@link SeverityAdvisor#LOCAL_ONLY}.
 *
 * <p>Blending policy: the brain can only <em>escalate</em>. We take the max of
 * the local detector severity and the brain's risk score, so a model
 * false-negative can never lower a concrete detector hit. When the brain is
 * unreachable, {@link AiBrainClient#triage} already returns a conservative local
 * fallback, which we pass straight through (never below the local severity).
 */
@Component
public class AiBrainSeverityAdvisor implements SeverityAdvisor {

    private final AiBrainClient brain;

    public AiBrainSeverityAdvisor(AiBrainClient brain) {
        this.brain = brain;
    }

    @Override
    public Advice refine(DefenseContext ctx, String layerName, double localSeverity,
                         Map<String, Object> signals) {
        Map<String, Object> telemetry = new HashMap<>(signals);
        telemetry.put("layer", layerName);
        telemetry.put("purpose", ctx.purpose());
        telemetry.put("role", ctx.role() == null ? "unknown" : ctx.role().name());
        telemetry.put("reg_no", ctx.regNo());
        telemetry.putIfAbsent("behavior_anomaly", localSeverity);

        AiBrainClient.BrainVerdict v = brain.triage(telemetry);
        double blended = Math.max(localSeverity, clamp01(v.riskScore()));
        return new Advice(blended, v.riskScore(), v.fromFallback(), v.requiresHumanApproval());
    }

    private static double clamp01(double d) {
        return d < 0 ? 0 : Math.min(d, 1.0);
    }
}
