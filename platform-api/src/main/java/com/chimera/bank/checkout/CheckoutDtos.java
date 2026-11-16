package com.chimera.bank.checkout;

import com.chimera.bank.fraud.ScoreReason;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class CheckoutDtos {
    private CheckoutDtos() {}

    public record CreateOrderRequest(
            @NotNull @DecimalMin("0.01") @DecimalMax("10000.00") BigDecimal amount,
            @NotBlank @Pattern(regexp = "^[A-Z]{3}$") String currency,
            @NotBlank @Size(max = 500) String note,
            @Pattern(regexp = "CHECKOUT|MANAGER_OVERRIDE") String purpose,
            String scenarioId,
            Telemetry telemetry
    ) {}

    public record AuthorizeRequest(Telemetry telemetry) {}

    public record StepUpRequest(@NotBlank @Pattern(regexp = "^[0-9]{6}$") String code, Telemetry telemetry) {}

    public record Telemetry(List<Double> keystrokeIntervalsMs, List<Double> keystrokeDwellMs, List<MouseMovement> mouseMovements) {
        public Telemetry {
            keystrokeIntervalsMs = sanitizeIntervals(keystrokeIntervalsMs);
            keystrokeDwellMs = sanitizeIntervals(keystrokeDwellMs);
            mouseMovements = mouseMovements == null ? List.of() : List.copyOf(mouseMovements.subList(0, Math.min(512, mouseMovements.size())));
        }

        private static List<Double> sanitizeIntervals(List<Double> values) {
            if (values == null) return List.of();
            return values.subList(0, Math.min(256, values.size())).stream()
                    .filter(value -> value != null && value >= 0 && value <= 60_000).toList();
        }
    }

    public record MouseMovement(double dx, double dy, double dtMs) {
        public MouseMovement {
            dx = Math.max(-100_000, Math.min(100_000, dx));
            dy = Math.max(-100_000, Math.min(100_000, dy));
            dtMs = Math.max(0, Math.min(60_000, dtMs));
        }
    }

    public record ScenarioRequest(@NotBlank String scenarioId) {}

    public record ScenarioView(String id, String title, String description, boolean simulated) {}

    public record VerificationChallengeView(
            String type,
            String prompt,
            Instant expiresAt,
            int attemptsRemaining,
            String demoAnswer,
            String demoNote
    ) {}

    public record OrderView(
            UUID id,
            String paypalOrderId,
            String paypalAuthorizationId,
            String captureId,
            OrderState state,
            BigDecimal amount,
            String currency,
            Double score,
            String action,
            List<ScoreReason> reasons,
            String scenarioId,
            boolean simulated,
            boolean stepUpRequired,
            String demoOtp,
            boolean receiptAvailable,
            Instant createdAt,
            Instant updatedAt
    ) {}
}
