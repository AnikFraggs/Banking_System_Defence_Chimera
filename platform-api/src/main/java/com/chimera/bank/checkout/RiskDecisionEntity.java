package com.chimera.bank.checkout;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "checkout_risk_decisions")
public class RiskDecisionEntity {
    @Id
    private UUID id;
    @Column(nullable = false)
    private UUID orderId;
    @Column(nullable = false)
    private String mode;
    @Column(nullable = false)
    private double score;
    @Column(nullable = false)
    private String action;
    @Lob
    private String reasonsJson;
    @Lob
    private String componentScoresJson;
    private String modelVersion;
    private String featureHash;
    private boolean fallback;
    private double latencyMs;
    @Column(nullable = false)
    private Instant createdAt;

    @PrePersist
    void prePersist() {
        if (id == null) id = UUID.randomUUID();
        if (createdAt == null) createdAt = Instant.now();
    }

    public UUID getId() { return id; }
    public void setId(UUID id) { this.id = id; }
    public UUID getOrderId() { return orderId; }
    public void setOrderId(UUID orderId) { this.orderId = orderId; }
    public String getMode() { return mode; }
    public void setMode(String mode) { this.mode = mode; }
    public double getScore() { return score; }
    public void setScore(double score) { this.score = score; }
    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }
    public String getReasonsJson() { return reasonsJson; }
    public void setReasonsJson(String reasonsJson) { this.reasonsJson = reasonsJson; }
    public String getComponentScoresJson() { return componentScoresJson; }
    public void setComponentScoresJson(String componentScoresJson) { this.componentScoresJson = componentScoresJson; }
    public String getModelVersion() { return modelVersion; }
    public void setModelVersion(String modelVersion) { this.modelVersion = modelVersion; }
    public String getFeatureHash() { return featureHash; }
    public void setFeatureHash(String featureHash) { this.featureHash = featureHash; }
    public boolean isFallback() { return fallback; }
    public void setFallback(boolean fallback) { this.fallback = fallback; }
    public double getLatencyMs() { return latencyMs; }
    public void setLatencyMs(double latencyMs) { this.latencyMs = latencyMs; }
    public Instant getCreatedAt() { return createdAt; }
}
