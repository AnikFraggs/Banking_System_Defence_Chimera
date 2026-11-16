package com.chimera.bank.fraud;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record ScoreRequest(
        String orderId,
        String paypalAuthorizationId,
        String mode,
        BigDecimal amount,
        String currency,
        @JsonFormat(shape = JsonFormat.Shape.STRING) Instant timestamp,
        String rail,
        Map<String, Double> cardFeatures,
        Telemetry telemetry,
        List<HistoryEvent> history,
        Evidence evidence,
        ScoreContext context
) {
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Telemetry(List<Double> keystrokeIntervalsMs, List<Double> keystrokeDwellMs,
                            List<MouseMovement> mouseMovements) {
        public Telemetry {
            keystrokeIntervalsMs = keystrokeIntervalsMs == null ? List.of() : List.copyOf(keystrokeIntervalsMs);
            keystrokeDwellMs = keystrokeDwellMs == null ? List.of() : List.copyOf(keystrokeDwellMs);
            mouseMovements = mouseMovements == null ? List.of() : List.copyOf(mouseMovements);
        }
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record MouseMovement(double x, double y, double intervalMs) {}

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record HistoryEvent(String deviceId, String destination, BigDecimal amount,
                               @JsonFormat(shape = JsonFormat.Shape.STRING) Instant timestamp) {}

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Evidence(Map<String, Object> metadata, String ocrText, String generatorMarker,
                           Double pixelResidual, byte[] imagePayload) {}

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record ScoreContext(Boolean stepUpVerified, Double priorEvidenceScore, String scenarioId) {}
}
