package com.chimera.bank.audit;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface AuditEventRepository extends JpaRepository<AuditEventEntity, Long> {
    Optional<AuditEventEntity> findTopByOrderByIdDesc();
    List<AuditEventEntity> findByOrderIdOrderByIdAsc(UUID orderId);
}
