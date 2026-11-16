package com.chimera.bank.ai;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.ClientHttpRequestFactories;
import org.springframework.boot.web.client.ClientHttpRequestFactorySettings;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.List;
import java.util.Map;

/**
 * Client for the Python "AI brain" service (ai-brain/app.py). {@code /v1/triage} is a
 * heuristic signature + anomaly scorer; {@code /v1/credit-application/score} is a logistic
 * regression trained on a synthetic credit-boost/CPN dataset with a red-flag knowledge base.
 *
 * <p>The Java platform owns money movement and the layered perimeter; it
 * delegates nuanced risk scoring to this service over HTTP. If the brain is
 * unreachable, {@link #triage} degrades gracefully to a conservative local
 * fallback and credit scoring fails closed to manual review.
 */
@Service
public class AiBrainClient {

    private static final Logger log = LoggerFactory.getLogger(AiBrainClient.class);

    private final RestClient client;
    private volatile boolean lastCallOk = false;

    public AiBrainClient(
            @Value("${chimera.ai-brain.base-url:http://localhost:8000}") String baseUrl,
            @Value("${chimera.ai-brain.connect-timeout-ms:2000}") long connectTimeoutMs,
            @Value("${chimera.ai-brain.read-timeout-ms:4000}") long readTimeoutMs) {
        // Bounded connect + read timeouts. Without these the JDK default is
        // INFINITE, so a stalled brain would hang /api/health indefinitely.
        ClientHttpRequestFactorySettings settings = ClientHttpRequestFactorySettings.DEFAULTS
                .withConnectTimeout(Duration.ofMillis(connectTimeoutMs))
                .withReadTimeout(Duration.ofMillis(readTimeoutMs));
        ClientHttpRequestFactory factory = ClientHttpRequestFactories.get(settings);
        this.client = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(factory)
                .build();
    }

    public record BrainVerdict(
            double riskScore,
            String enforcedRecommendation,
            boolean requiresHumanApproval,
            boolean fromFallback) {
    }

    /**
     * Full triage response including the manager-facing action and detected
     * threats. Used by the manager threat console; degrades to the same
     * conservative fallback as {@link #triage} when the brain is down.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> triageDetailed(Map<String, Object> telemetry) {
        try {
            Map<String, Object> response = client.post()
                    .uri("/v1/triage")
                    .body(Map.of("telemetry", telemetry, "include_llm_summary", false))
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, (req, res) -> {
                        throw new IllegalStateException("brain returned " + res.getStatusCode());
                    })
                    .body(Map.class);
            lastCallOk = true;
            return response == null ? Map.of() : response;
        } catch (Exception e) {
            lastCallOk = false;
            log.warn("AI brain unavailable ({}); using conservative local fallback.", e.toString());
            BrainVerdict v = conservativeFallback(telemetry);
            return Map.of(
                    "risk_score", v.riskScore(),
                    "enforced_recommendation", v.enforcedRecommendation(),
                    "requires_human_approval", v.requiresHumanApproval(),
                    "detected_threats", java.util.List.of(),
                    "manager_action", "AI brain offline — applying conservative local policy: "
                            + v.enforcedRecommendation() + ".",
                    "summary", "AI brain unreachable; local fallback verdict.",
                    "from_fallback", true);
        }
    }

    /** Returns model-artifact readiness from the brain's /health, or false if down. */
    public boolean brainHealthy() {
        try {
            Map<?, ?> body = client.get().uri("/health").retrieve().body(Map.class);
            lastCallOk = body != null && "ok".equals(body.get("status"));
            return lastCallOk;
        } catch (Exception e) {
            lastCallOk = false;
            return false;
        }
    }

    public boolean lastCallOk() {
        return lastCallOk;
    }

    /**
     * Scores a credit application (derived features only) for credit-boost / CPN fraud.
     * Brain validation errors surface as 400 without echoing the brain's detail, which can
     * contain the rejected input; an unreachable brain fails closed to manual review.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> scoreCreditApplication(Map<String, Object> application) {
        try {
            Map<String, Object> response = client.post()
                    .uri("/v1/credit-application/score")
                    .body(application)
                    .retrieve()
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                                "Credit application failed validation (derived features only; no raw identifiers).");
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new IllegalStateException("brain returned " + res.getStatusCode());
                    })
                    .body(Map.class);
            lastCallOk = true;
            if (response == null) {
                throw new IllegalStateException("brain returned an empty body");
            }
            return response;
        } catch (ResponseStatusException e) {
            lastCallOk = true;
            throw e;
        } catch (Exception e) {
            lastCallOk = false;
            log.warn("AI brain unavailable for credit scoring ({}); failing closed to manual review.", e.toString());
            return Map.of(
                    "decision", "manual_review",
                    "requires_human_review", true,
                    "auto_decline", false,
                    "red_flags", List.of(),
                    "recommended_checks", List.of("ecbsv_consent_ssn_verification",
                            "income_verification_from_payroll_or_bank_data"),
                    "model_loaded", false,
                    "summary", "Credit brain unreachable; failing closed to manual review.",
                    "from_fallback", true);
        }
    }

    @SuppressWarnings("unchecked")
    public BrainVerdict triage(Map<String, Object> telemetry) {
        try {
            Map<String, Object> response = client.post()
                    .uri("/v1/triage")
                    .body(Map.of("telemetry", telemetry, "include_llm_summary", false))
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, (req, res) -> {
                        throw new IllegalStateException("brain returned " + res.getStatusCode());
                    })
                    .body(Map.class);
            lastCallOk = true;
            double risk = ((Number) response.getOrDefault("risk_score", 0.0)).doubleValue();
            String rec = String.valueOf(response.getOrDefault("enforced_recommendation", "step_up"));
            boolean approval = Boolean.TRUE.equals(response.get("requires_human_approval"));
            return new BrainVerdict(risk, rec, approval, false);
        } catch (Exception e) {
            lastCallOk = false;
            log.warn("AI brain unavailable ({}); using conservative local fallback.", e.toString());
            return conservativeFallback(telemetry);
        }
    }

    /**
     * Conservative fallback when the brain is down: prefer safety without over-
     * blocking. Elevated behavior anomaly or an invalid workload identity map to
     * a step-up / isolate recommendation.
     */
    private BrainVerdict conservativeFallback(Map<String, Object> t) {
        double anomaly = toDouble(t.get("behavior_anomaly"));
        boolean workloadInvalid = "workload".equals(t.get("entry_context"))
                && Boolean.FALSE.equals(t.get("workload_identity_valid"));
        if (workloadInvalid) {
            return new BrainVerdict(0.9, "isolate_session", true, true);
        }
        if (anomaly >= 0.6) {
            return new BrainVerdict(anomaly, "constrain", true, true);
        }
        if (anomaly >= 0.35) {
            return new BrainVerdict(anomaly, "step_up", false, true);
        }
        return new BrainVerdict(anomaly, "allow", false, true);
    }

    private static double toDouble(Object o) {
        return o instanceof Number n ? n.doubleValue() : 0.0;
    }
}
