package com.chimera.bank.payment;

import org.springframework.data.jpa.repository.JpaRepository;

public interface WebhookEventRepository extends JpaRepository<WebhookEventEntity, String> {
}
