package com.chimera.bank.ai;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * Manager-facing console over the GenAI brain. The manager can submit a
 * suspicious payload/telemetry and receive a risk verdict plus a concrete
 * recommended action, and can poll brain health.
 */
@RestController
@RequestMapping("/api/ai-brain")
public class AiBrainController {

    private final AuthService auth;
    private final AiBrainClient brain;

    public AiBrainController(AuthService auth, AiBrainClient brain) {
        this.auth = auth;
        this.brain = brain;
    }

    @GetMapping("/health")
    public Map<String, Object> health(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.MANAGER, Role.ACCOUNTANT);
        boolean healthy = brain.brainHealthy();
        return Map.of("healthy", healthy, "detail", healthy ? "AI brain online." : "AI brain offline (local fallback active).");
    }

    @PostMapping("/triage")
    public Map<String, Object> triage(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @RequestBody Map<String, Object> telemetry) {
        auth.requireOneOf(authorization, Role.MANAGER, Role.ACCOUNTANT);
        Map<String, Object> payload = new HashMap<>(telemetry == null ? Map.of() : telemetry);
        return brain.triageDetailed(payload);
    }
}
