package com.chimera.bank.checkout;

import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface CheckoutOrderRepository extends JpaRepository<CheckoutOrderEntity, UUID> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select o from CheckoutOrderEntity o where o.id = :id")
    Optional<CheckoutOrderEntity> findForUpdate(@Param("id") UUID id);

    Optional<CheckoutOrderEntity> findByPaypalOrderId(String paypalOrderId);
    List<CheckoutOrderEntity> findTop100ByOrderByCreatedAtDesc();
}
