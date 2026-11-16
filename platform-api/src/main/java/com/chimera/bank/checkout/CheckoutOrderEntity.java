package com.chimera.bank.checkout;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "checkout_orders", indexes = {
        @Index(name = "idx_orders_owner_created", columnList = "username, createdAt"),
        @Index(name = "idx_orders_state", columnList = "state"),
        @Index(name = "idx_orders_created", columnList = "createdAt")
})
public class CheckoutOrderEntity {
    @Id
    private UUID id;
    @Version
    private Long version;
    @Column(nullable = false)
    private String username;
    @Column(nullable = false)
    private String buyerRole;
    @Column(unique = true)
    private String paypalOrderId;
    @Column(unique = true)
    private String paypalAuthorizationId;
    @Column(unique = true)
    private String captureId;
    @Column(nullable = false, precision = 19, scale = 2)
    private BigDecimal amount;
    @Column(nullable = false, length = 3)
    private String currency;
    @Column(nullable = false, length = 500)
    private String note;
    @Column(nullable = false)
    private String purpose;
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private OrderState state;
    private Double score;
    private String action;
    @JdbcTypeCode(SqlTypes.LONGVARCHAR)
    private String reasonsJson;
    private String scenarioId;
    @Column(nullable = false)
    private boolean simulated;
    @Column(nullable = false)
    private boolean receiptAvailable;
    @Column(nullable = false)
    private Instant createdAt;
    @Column(nullable = false)
    private Instant updatedAt;

    @PrePersist
    void prePersist() {
        if (id == null) id = UUID.randomUUID();
        if (createdAt == null) createdAt = Instant.now();
        updatedAt = createdAt;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = Instant.now();
    }

    public UUID getId() { return id; }
    public void setId(UUID id) { this.id = id; }
    public Long getVersion() { return version; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getBuyerRole() { return buyerRole; }
    public void setBuyerRole(String buyerRole) { this.buyerRole = buyerRole; }
    public String getPaypalOrderId() { return paypalOrderId; }
    public void setPaypalOrderId(String paypalOrderId) { this.paypalOrderId = paypalOrderId; }
    public String getPaypalAuthorizationId() { return paypalAuthorizationId; }
    public void setPaypalAuthorizationId(String paypalAuthorizationId) { this.paypalAuthorizationId = paypalAuthorizationId; }
    public String getCaptureId() { return captureId; }
    public void setCaptureId(String captureId) { this.captureId = captureId; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
    public String getNote() { return note; }
    public void setNote(String note) { this.note = note; }
    public String getPurpose() { return purpose; }
    public void setPurpose(String purpose) { this.purpose = purpose; }
    public OrderState getState() { return state; }
    public void setState(OrderState state) { this.state = state; }
    public Double getScore() { return score; }
    public void setScore(Double score) { this.score = score; }
    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }
    public String getReasonsJson() { return reasonsJson; }
    public void setReasonsJson(String reasonsJson) { this.reasonsJson = reasonsJson; }
    public String getScenarioId() { return scenarioId; }
    public void setScenarioId(String scenarioId) { this.scenarioId = scenarioId; }
    public boolean isSimulated() { return simulated; }
    public void setSimulated(boolean simulated) { this.simulated = simulated; }
    public boolean isReceiptAvailable() { return receiptAvailable; }
    public void setReceiptAvailable(boolean receiptAvailable) { this.receiptAvailable = receiptAvailable; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
}
