package com.chimera.bank.cases;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface CaseRepository extends JpaRepository<CaseEntity, UUID> {
    Optional<CaseEntity> findByOrderId(UUID orderId);
    List<CaseEntity> findTop50ByOrderByUpdatedAtDesc();
}
