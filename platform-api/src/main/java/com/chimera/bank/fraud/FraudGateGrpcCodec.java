package com.chimera.bank.fraud;

import com.google.protobuf.ByteString;

import java.util.LinkedHashMap;
import java.util.Map;

/** Lossless typed mapping between the HTTP DTOs and the fraud-gate protobuf contract. */
public final class FraudGateGrpcCodec {
    private FraudGateGrpcCodec() {}

    public static com.chimera.bank.fraud.grpc.ScoreRequest toProto(ScoreRequest source) {
        com.chimera.bank.fraud.grpc.ScoreRequest.Builder target =
                com.chimera.bank.fraud.grpc.ScoreRequest.newBuilder()
                        .setOrderId(nullToEmpty(source.orderId()))
                        .setPaypalAuthorizationId(nullToEmpty(source.paypalAuthorizationId()))
                        .setMode(nullToEmpty(source.mode()))
                        .setAmount(source.amount() == null ? "0" : source.amount().toPlainString())
                        .setCurrency(nullToEmpty(source.currency()))
                        .setTimestamp(source.timestamp() == null ? "" : source.timestamp().toString())
                        .setRail(nullToEmpty(source.rail()));
        if (source.cardFeatures() != null) target.putAllCardFeatures(source.cardFeatures());
        if (source.telemetry() != null) {
            com.chimera.bank.fraud.grpc.Telemetry.Builder telemetry =
                    com.chimera.bank.fraud.grpc.Telemetry.newBuilder()
                            .addAllKeystrokeIntervalsMs(source.telemetry().keystrokeIntervalsMs())
                            .addAllKeystrokeDwellMs(source.telemetry().keystrokeDwellMs());
            for (ScoreRequest.MouseMovement movement : source.telemetry().mouseMovements()) {
                telemetry.addMouseMovements(com.chimera.bank.fraud.grpc.MouseMovement.newBuilder()
                        .setX(movement.x())
                        .setY(movement.y())
                        .setIntervalMs(movement.intervalMs())
                        .build());
            }
            target.setTelemetry(telemetry.build());
        }
        for (ScoreRequest.HistoryEvent event : source.history() == null ? java.util.List.<ScoreRequest.HistoryEvent>of() : source.history()) {
            target.addHistory(com.chimera.bank.fraud.grpc.HistoryEvent.newBuilder()
                    .setDeviceId(nullToEmpty(event.deviceId()))
                    .setDestination(nullToEmpty(event.destination()))
                    .setAmount(event.amount() == null ? "0" : event.amount().toPlainString())
                    .setTimestamp(event.timestamp() == null ? "" : event.timestamp().toString())
                    .build());
        }
        if (source.evidence() != null) {
            com.chimera.bank.fraud.grpc.Evidence.Builder evidence =
                    com.chimera.bank.fraud.grpc.Evidence.newBuilder()
                            .setOcrText(nullToEmpty(source.evidence().ocrText()))
                            .setGeneratorMarker(nullToEmpty(source.evidence().generatorMarker()))
                            .setPixelResidual(source.evidence().pixelResidual() == null ? 0.0 : source.evidence().pixelResidual());
            if (source.evidence().imagePayload() != null) {
                evidence.setImagePayload(ByteString.copyFrom(source.evidence().imagePayload()));
            }
            if (source.evidence().metadata() != null) {
                Map<String, String> metadata = new LinkedHashMap<>();
                source.evidence().metadata().forEach((key, value) ->
                        metadata.put(key, value == null ? "" : String.valueOf(value)));
                evidence.putAllMetadata(metadata);
            }
            target.setEvidence(evidence.build());
        }
        if (source.context() != null) {
            target.setContext(com.chimera.bank.fraud.grpc.ScoreContext.newBuilder()
                    .setStepUpVerified(Boolean.TRUE.equals(source.context().stepUpVerified()))
                    .setPriorEvidenceScore(source.context().priorEvidenceScore() == null
                            ? 0.0 : source.context().priorEvidenceScore())
                    .setScenarioId(nullToEmpty(source.context().scenarioId()))
                    .build());
        }
        return target.build();
    }

    public static ScoreResponse fromProto(com.chimera.bank.fraud.grpc.ScoreResponse source) {
        return new ScoreResponse(
                source.getDecisionId(),
                source.getScore(),
                source.getAction(),
                source.getReasonsList().stream()
                        .map(reason -> new ScoreReason(reason.getCode(), reason.getMessage(),
                                reason.getComponent(), reason.getScore()))
                        .toList(),
                Map.copyOf(source.getComponentScoresMap()),
                source.getModelVersion(),
                source.getFeatureHash(),
                source.getFallback(),
                source.getLatencyMs());
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
