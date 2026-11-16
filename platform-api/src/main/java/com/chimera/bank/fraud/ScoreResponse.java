package com.chimera.bank.fraud;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record ScoreResponse(
        String decisionId,
        Double score,
        String action,
        List<ScoreReason> reasons,
        Map<String, Double> componentScores,
        String modelVersion,
        String featureHash,
        boolean fallback,
        double latencyMs
) {
    public boolean valid() {
        return score != null && score >= 0 && score <= 1
                && action != null && List.of("CAPTURE", "CHALLENGE", "VOID").contains(action)
                && reasons != null;
    }
}
