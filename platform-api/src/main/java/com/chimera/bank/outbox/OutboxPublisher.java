package com.chimera.bank.outbox;

/** Broker transport for committed outbox rows. Implementations must be idempotent-friendly (at-least-once). */
public interface OutboxPublisher {
    void publish(OutboxEventEntity event);

    void deadLetter(OutboxEventEntity event);
}