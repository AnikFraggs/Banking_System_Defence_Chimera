package com.chimera.bank.checkout;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "checkout_step_up_challenges")
public class StepUpChallengeEntity {
    @Id
    private UUID id;
    @Column(nullable = false, unique = true)
    private UUID orderId;
    @Column(nullable = false, length = 64)
    private String codeHash;
    @Column(nullable = false)
    private Instant expiresAt;
    @Column(nullable = false)
    private int attempts;
    private Instant consumedAt;
    @Column(length = 32)
    private String challengeType;
    @Column(length = 1000)
    private String prompt;
    @Column(length = 32)
    private String invoiceOrderAmount;
    @Column(length = 32)
    private String invoiceAmount;
    @Column(length = 3)
    private String invoiceCurrency;

    @PrePersist
    void prePersist() {
        if (id == null) id = UUID.randomUUID();
    }

    public UUID getId() { return id; }
    public UUID getOrderId() { return orderId; }
    public void setOrderId(UUID orderId) { this.orderId = orderId; }
    public String getCodeHash() { return codeHash; }
    public void setCodeHash(String codeHash) { this.codeHash = codeHash; }
    public Instant getExpiresAt() { return expiresAt; }
    public void setExpiresAt(Instant expiresAt) { this.expiresAt = expiresAt; }
    public int getAttempts() { return attempts; }
    public void setAttempts(int attempts) { this.attempts = attempts; }
    public Instant getConsumedAt() { return consumedAt; }
    public void setConsumedAt(Instant consumedAt) { this.consumedAt = consumedAt; }
    public String getChallengeType() { return challengeType; }
    public void setChallengeType(String challengeType) { this.challengeType = challengeType; }
    public String getPrompt() { return prompt; }
    public void setPrompt(String prompt) { this.prompt = prompt; }
    public String getInvoiceOrderAmount() { return invoiceOrderAmount; }
    public void setInvoiceOrderAmount(String invoiceOrderAmount) { this.invoiceOrderAmount = invoiceOrderAmount; }
    public String getInvoiceAmount() { return invoiceAmount; }
    public void setInvoiceAmount(String invoiceAmount) { this.invoiceAmount = invoiceAmount; }
    public String getInvoiceCurrency() { return invoiceCurrency; }
    public void setInvoiceCurrency(String invoiceCurrency) { this.invoiceCurrency = invoiceCurrency; }
}
