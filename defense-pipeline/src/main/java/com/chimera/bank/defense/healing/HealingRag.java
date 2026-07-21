package com.chimera.bank.defense.healing;

import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Retrieval store of reviewed remediation playbooks (the "RAG healing" corpus).
 *
 * <p>Given a threat class inferred from the failing layer's verdict, it returns
 * the matching bounded, reversible playbook. In production this is backed by the
 * same reviewed-runbook retrieval service as the Python brain's RAG; here it is
 * a small curated in-memory corpus so healing is deterministic and testable.
 */
@Component
public class HealingRag {

    private final Map<String, HealingPlaybook> corpus = Map.of(
            "ip_reputation", new HealingPlaybook(
                    "ip_reputation", "Network-source containment",
                    List.of("re-resolve source reputation", "apply per-IP rate limit",
                            "require session re-auth from a known device"),
                    0.85),
            "rbac_violation", new HealingPlaybook(
                    "rbac_violation", "Authorization hardening",
                    List.of("revoke escalated scope", "reset session to least privilege",
                            "notify accountant/manager of attempted escalation"),
                    0.95),
            "purpose_mismatch", new HealingPlaybook(
                    "purpose_mismatch", "Intent revalidation",
                    List.of("reject tampered payload", "request fresh signed intent",
                            "recompute purpose coherence"),
                    0.80),
            "injection_leak", new HealingPlaybook(
                    "injection_leak", "Prompt-injection / stego neutralization",
                    List.of("strip invisible + bidi characters", "quarantine the raw payload",
                            "rotate any exposed canary token", "re-scan sanitized text"),
                    0.70),
            "automation", new HealingPlaybook(
                    "automation", "Anti-automation step-up",
                    List.of("issue ghost-text human challenge", "throttle the session",
                            "escalate to MFA / WebAuthn"),
                    0.75),
            "generic", new HealingPlaybook(
                    "generic", "Generic containment",
                    List.of("isolate session scope", "increase monitoring",
                            "hold for analyst review"),
                    0.60));

    /** Map a failing layer name to a threat class, then retrieve its playbook. */
    public Optional<HealingPlaybook> retrieveForLayer(String layerName) {
        String threatClass = switch (layerName) {
            case "L1_ip_reputation" -> "ip_reputation";
            case "L2_role_status" -> "rbac_violation";
            case "L3_purpose" -> "purpose_mismatch";
            case "L4_injection_leak" -> "injection_leak";
            case "L5_human_verification" -> "automation";
            default -> "generic";
        };
        return Optional.ofNullable(corpus.get(threatClass));
    }

    public HealingPlaybook generic() {
        return corpus.get("generic");
    }
}
