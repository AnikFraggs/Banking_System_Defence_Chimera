package com.chimera.bank.defense.ai;

import com.chimera.bank.common.defense.DefenseContext;

import java.util.Map;

/**
 * Seam through which the AI-security layers (L4 injection/leak, L5 human
 * verification) can have their locally-computed severity refined by the external
 * "AI brain" (the Python XGBoost + RAG + RL triage service).
 *
 * <p>The defense-pipeline module deliberately does NOT depend on platform-api or
 * on any HTTP client. It only knows this interface; platform-api provides the
 * implementation that actually calls {@code AiBrainClient}. In tests (and when
 * the brain is unreachable) the {@link #LOCAL_ONLY} no-op is used, so the layers
 * degrade gracefully to their local detector severity.
 */
public interface SeverityAdvisor {

    /**
     * Refine a layer's locally-detected severity using the brain's risk model.
     *
     * @param ctx           the request context (telemetry source)
     * @param layerName     the calling layer (e.g. {@code L4_injection_leak})
     * @param localSeverity severity in [0,1] computed by the layer's own detectors
     * @param signals       extra detector signals to feed the brain as telemetry
     * @return a blended {@link Advice}; never null. Implementations MUST fail safe
     * (return at least {@code localSeverity}) when the brain is unavailable.
     */
    Advice refine(DefenseContext ctx, String layerName, double localSeverity, Map<String, Object> signals);

    /**
     * @param severity          blended severity in [0,1]
     * @param brainRiskScore    the raw brain risk score, or the local value on fallback
     * @param fromFallback      true if the brain was unreachable and the local value was used
     * @param requiresHumanApproval brain signalled that a human must approve
     */
    record Advice(double severity, double brainRiskScore, boolean fromFallback,
                  boolean requiresHumanApproval) {
    }

    /** No-op advisor: severity stays exactly local. Used in unit tests / offline. */
    SeverityAdvisor LOCAL_ONLY = (ctx, layer, local, signals) ->
            new Advice(local, local, true, false);
}
