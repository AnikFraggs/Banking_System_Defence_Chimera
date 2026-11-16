package com.chimera.bank.fraud;

import java.util.List;
import java.util.Map;
import java.util.UUID;

final class FraudGateFallback {
    private FraudGateFallback() {}

    static ScoreResponse challenge(String code, String message, double latencyMs) {
        return new ScoreResponse(UUID.randomUUID().toString(), 0.5, "CHALLENGE",
                List.of(new ScoreReason(code, message, "GATE", 0.5)), Map.of(),
                "unavailable", "", true, latencyMs);
    }
}
