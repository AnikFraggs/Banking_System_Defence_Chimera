package com.chimera.bank.checkout;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface RiskDecisionRepository extends JpaRepository<RiskDecisionEntity, UUID> {
    List<RiskDecisionEntity> findByOrderIdOrderByCreatedAtAsc(UUID orderId);
}
