package com.chimera.bank.defense;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "deception_vault_entries", indexes = {
        @Index(name = "idx_vault_correlation", columnList = "correlation_id")
})
public class DeceptionVaultEntity {
    @Id
    @Column(name = "vault_id", length = 128)
    private String vaultId;

    @Column(name = "correlation_id", length = 128, nullable = false)
    private String correlationId;

    @Column(name = "quarantined_at", nullable = false)
    private Instant quarantinedAt;

    @Column(name = "reason", length = 500, nullable = false)
    private String reason;

    @Column(name = "encrypted_snapshot", columnDefinition = "TEXT", nullable = false)
    private String encryptedSnapshot;

    @Column(name = "status", length = 32, nullable = false)
    private String status;

    public DeceptionVaultEntity() {}

    public DeceptionVaultEntity(String vaultId, String correlationId, Instant quarantinedAt,
                                String reason, String encryptedSnapshot, String status) {
        this.vaultId = vaultId;
        this.correlationId = correlationId;
        this.quarantinedAt = quarantinedAt;
        this.reason = reason;
        this.encryptedSnapshot = encryptedSnapshot;
        this.status = status;
    }

    public String getVaultId() { return vaultId; }
    public void setVaultId(String vaultId) { this.vaultId = vaultId; }

    public String getCorrelationId() { return correlationId; }
    public void setCorrelationId(String correlationId) { this.correlationId = correlationId; }

    public Instant getQuarantinedAt() { return quarantinedAt; }
    public void setQuarantinedAt(Instant quarantinedAt) { this.quarantinedAt = quarantinedAt; }

    public String getReason() { return reason; }
    public void setReason(String reason) { this.reason = reason; }

    public String getEncryptedSnapshot() { return encryptedSnapshot; }
    public void setEncryptedSnapshot(String encryptedSnapshot) { this.encryptedSnapshot = encryptedSnapshot; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
