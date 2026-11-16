package com.chimera.bank.payment;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;
import java.util.Optional;
import java.util.UUID;

public interface PayPalOperationRepository extends JpaRepository<PayPalOperationEntity, UUID> {
    Optional<PayPalOperationEntity> findFirstByOperationTypeAndOrderIdAndRequestBodyHashAndStatusInOrderByCreatedAtDesc(
            String operationType, UUID orderId, String requestBodyHash, Collection<String> statuses);

    @Override
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    <S extends PayPalOperationEntity> S saveAndFlush(S entity);
}
