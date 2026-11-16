package com.chimera.bank.checkout;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface StepUpChallengeRepository extends JpaRepository<StepUpChallengeEntity, UUID> {
    Optional<StepUpChallengeEntity> findByOrderId(UUID orderId);
}
