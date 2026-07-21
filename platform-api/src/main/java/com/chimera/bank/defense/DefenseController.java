package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Runs an inbound request through the ordered defense rings and returns the
 * full verdict trace. This endpoint is used by the front-end and internal
 * flows to gate an action before any money movement occurs.
 */
@RestController
@RequestMapping("/api/defense")
public class DefenseController {

    private final DefensePipeline pipeline;

    public DefenseController(DefensePipeline pipeline) {
        this.pipeline = pipeline;
    }

    public record EvaluateRequest(
            @NotBlank String regNo,
            @NotBlank String role,
            @NotBlank String purpose,
            String payload,
            Boolean humanChallengePassed,
            Boolean selfHealFailed) {
    }

    /** Serialization-friendly view of a pipeline run for the API/front-end. */
    public record EvaluateResponse(
            String correlationId,
            String decision,
            String haltedAtLayer,
            String reason,
            double severity,
            boolean allowed,
            List<LayerVerdict> trace) {

        static EvaluateResponse from(DefenseResult r) {
            LayerVerdict f = r.finalVerdict();
            return new EvaluateResponse(
                    r.correlationId(),
                    f.decision().name(),
                    f.layer(),
                    f.reason(),
                    f.severity(),
                    r.allowed(),
                    r.trace());
        }
    }

    @PostMapping("/evaluate")
    public ResponseEntity<EvaluateResponse> evaluate(
            @RequestBody EvaluateRequest req,
            @RequestHeader(value = "X-Forwarded-For", required = false) String forwardedIp,
            @RequestHeader(value = "X-Real-IP", required = false) String realIp) {

        String ip = forwardedIp != null ? forwardedIp : realIp;
        DefenseContext ctx = new DefenseContext(
                "cor-" + UUID.randomUUID(),
                Instant.now(),
                ip,
                req.regNo(),
                parseRole(req.role()),
                req.purpose(),
                req.payload());

        if (Boolean.TRUE.equals(req.humanChallengePassed())) {
            ctx.addSignal("human_challenge_passed", true);
        }
        if (Boolean.TRUE.equals(req.selfHealFailed())) {
            ctx.addSignal("self_heal_failed", true);
        }

        DefenseResult result = pipeline.evaluate(ctx);
        return ResponseEntity.ok(EvaluateResponse.from(result));
    }

    private static Role parseRole(String role) {
        try {
            return Role.valueOf(role.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            return null; // L2 will block an unknown role.
        }
    }
}
