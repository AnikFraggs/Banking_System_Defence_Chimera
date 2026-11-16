package com.chimera.bank.idempotency;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import org.springframework.data.domain.Persistable;

import java.time.Instant;

@Entity
@Table(name = "idempotency_keys")
public class IdempotencyKeyEntity implements Persistable<String> {
    public enum Status { IN_PROGRESS, COMPLETED }

    @Id
    @Column(length = 128)
    private String id;
    @Column(nullable = false, length = 64)
    private String scope;
    @Column(nullable = false, length = 64)
    private String requestHash;
    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;
    @JdbcTypeCode(SqlTypes.LONGVARCHAR)
    private String responseJson;
    @Column(nullable = false)
    private Instant createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) createdAt = Instant.now();
    }

    @Override
    public String getId() { return id; }

    // Assigned id: persist (not merge) while new, so @PrePersist's createdAt survives the completion update.
    @Override
    public boolean isNew() { return createdAt == null; }

    public void setId(String id) { this.id = id; }
    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }
    public String getRequestHash() { return requestHash; }
    public void setRequestHash(String requestHash) { this.requestHash = requestHash; }
    public Status getStatus() { return status; }
    public void setStatus(Status status) { this.status = status; }
    public String getResponseJson() { return responseJson; }
    public void setResponseJson(String responseJson) { this.responseJson = responseJson; }
    public Instant getCreatedAt() { return createdAt; }
}