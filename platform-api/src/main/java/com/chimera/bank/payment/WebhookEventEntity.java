package com.chimera.bank.payment;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "paypal_webhook_events")
public class WebhookEventEntity {
    @Id
    @Column(name = "event_id", length = 100)
    private String eventId;

    @Column(name = "event_type", length = 150)
    private String eventType;

    @Column(name = "payload_hash", nullable = false, length = 64)
    private String payloadHash;

    @Column(name = "processed_at", nullable = false)
    private Instant processedAt;

    public WebhookEventEntity() {
    }

    public WebhookEventEntity(String eventId, String eventType, String payloadHash, Instant processedAt) {
        this.eventId = eventId;
        this.eventType = eventType;
        this.payloadHash = payloadHash;
        this.processedAt = processedAt;
    }

    public String getEventId() {
        return eventId;
    }

    public void setEventId(String eventId) {
        this.eventId = eventId;
    }

    public String getEventType() {
        return eventType;
    }

    public void setEventType(String eventType) {
        this.eventType = eventType;
    }

    public String getPayloadHash() {
        return payloadHash;
    }

    public void setPayloadHash(String payloadHash) {
        this.payloadHash = payloadHash;
    }

    public Instant getProcessedAt() {
        return processedAt;
    }

    public void setProcessedAt(Instant processedAt) {
        this.processedAt = processedAt;
    }
}
