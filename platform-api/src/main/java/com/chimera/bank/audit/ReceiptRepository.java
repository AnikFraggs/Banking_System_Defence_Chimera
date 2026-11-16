package com.chimera.bank.audit;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface ReceiptRepository extends JpaRepository<ReceiptEntity, UUID> {
    Optional<ReceiptEntity> findByOrderId(UUID orderId);
}
