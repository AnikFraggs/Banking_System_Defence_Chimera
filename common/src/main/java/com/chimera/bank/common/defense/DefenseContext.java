package com.chimera.bank.common.defense;

import com.chimera.bank.common.rbac.Role;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The request context threaded through every defense layer. It is mutable only
 * for the annotations layers add (signals, scores); the original request facts
 * are immutable. No raw credentials or full PANs are ever stored here.
 */
public final class DefenseContext {

    private final String correlationId;
    private final Instant receivedAt;
    private final String sourceIp;
    private final String regNo;
    private final Role role;
    private final String purpose;      // declared intent: "transfer" | "deposit" | ...
    private final String payload;      // free-text / structured intent to inspect (never secrets)
    private final Map<String, Object> signals = new LinkedHashMap<>();

    public DefenseContext(String correlationId, Instant receivedAt, String sourceIp,
                          String regNo, Role role, String purpose, String payload) {
        this.correlationId = correlationId;
        this.receivedAt = receivedAt;
        this.sourceIp = sourceIp;
        this.regNo = regNo;
        this.role = role;
        this.purpose = purpose;
        this.payload = payload == null ? "" : payload;
    }

    public void addSignal(String key, Object value) {
        signals.put(key, value);
    }

    public String correlationId() {
        return correlationId;
    }

    public Instant receivedAt() {
        return receivedAt;
    }

    public String sourceIp() {
        return sourceIp;
    }

    public String regNo() {
        return regNo;
    }

    public Role role() {
        return role;
    }

    public String purpose() {
        return purpose;
    }

    public String payload() {
        return payload;
    }

    public Map<String, Object> signals() {
        return signals;
    }
}
