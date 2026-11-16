package com.chimera.bank.audit;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.EntityManager;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

@Service
public class AuditLedgerService {
    private final AuditEventRepository repository;
    private final AuditCrypto crypto;
    private final ObjectMapper objectMapper;
    private final EntityManager entityManager;
    private final boolean postgresLock;

    public AuditLedgerService(AuditEventRepository repository, AuditCrypto crypto, ObjectMapper objectMapper,
                              EntityManager entityManager,
                              @Value("${chimera.checkout.audit.postgres-lock:true}") boolean postgresLock) {
        this.repository = repository;
        this.crypto = crypto;
        this.objectMapper = objectMapper;
        this.entityManager = entityManager;
        this.postgresLock = postgresLock;
    }

    // Keep the global chain serialization lock only for this short append transaction.
    // A REQUIRED transaction would retain the lock until CheckoutService finishes fraud scoring
    // and all remaining work, serializing unrelated checkouts behind that remote call.
    // REQUIRES_NEW also makes an audit record durable when the surrounding checkout later rolls back.
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public AuditEventEntity append(UUID orderId, String eventType, Map<String, ?> details) {
        try {
            if (postgresLock) {
                entityManager.createNativeQuery("select pg_advisory_xact_lock(741852963)").getSingleResult();
            }
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("orderId", orderId.toString());
            payload.put("eventType", eventType);
            payload.put("details", details);
            String canonical = objectMapper.writeValueAsString(payload);
            String previousHash = repository.findTopByOrderByIdDesc()
                    .map(AuditEventEntity::getCurrentHash).orElse("0".repeat(64));
            String currentHash = crypto.sha256(previousHash + canonical);

            AuditEventEntity event = new AuditEventEntity();
            event.setOrderId(orderId);
            event.setEventType(eventType);
            event.setPayload(canonical);
            event.setPreviousHash(previousHash);
            event.setCurrentHash(currentHash);
            event.setHmac(crypto.hmac(currentHash));
            event.setKeyVersion(crypto.keyVersion());
            return repository.saveAndFlush(event);
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("Could not append checkout audit event", e);
        }
    }
}
