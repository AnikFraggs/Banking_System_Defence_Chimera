package com.chimera.bank.fraud;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record ScoreReason(String code, String message, String component, Double score) {
    public ScoreReason(String code, String message) {
        this(code, message, "GATE", 0.5);
    }
}
