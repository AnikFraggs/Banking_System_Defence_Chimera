package com.chimera.bank.outbox;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;

/**
 * Polls committed outbox rows and publishes them at-least-once. Each failed attempt is retried on a
 * later poll; after the attempt budget is exhausted the row is moved to a dead-letter queue so a
 * poison event cannot block the relay forever.
 */
@Component
@ConditionalOnProperty(name = "chimera.outbox.relay.enabled", havingValue = "true", matchIfMissing = true)
public class OutboxRelay {
    private static final Logger log = LoggerFactory.getLogger(OutboxRelay.class);

    private final OutboxEventRepository repository;
    private final OutboxPublisher publisher;
    private final Counter published;
    private final Counter dead;
    private final int maxAttempts;

    public OutboxRelay(OutboxEventRepository repository, OutboxPublisher publisher, MeterRegistry registry,
                       @Value("${chimera.outbox.max-attempts:5}") int maxAttempts) {
        this.repository = repository;
        this.publisher = publisher;
        this.maxAttempts = maxAttempts;
        this.published = Counter.builder("chimera_outbox_published_total")
                .description("Outbox events successfully published to the broker").register(registry);
        this.dead = Counter.builder("chimera_outbox_dead_total")
                .description("Outbox events moved to the dead-letter queue").register(registry);
    }

    @Scheduled(fixedDelayString = "${chimera.outbox.relay.poll-ms:1000}")
    @Transactional
    public void relay() {
        List<OutboxEventEntity> batch = repository.findTop50ByStatusOrderByCreatedAtAsc(OutboxEventEntity.Status.NEW);
        for (OutboxEventEntity event : batch) {
            try {
                publisher.publish(event);
                event.setStatus(OutboxEventEntity.Status.PUBLISHED);
                event.setPublishedAt(Instant.now());
                published.increment();
            } catch (RuntimeException e) {
                event.setAttempts(event.getAttempts() + 1);
                event.setLastError(truncate(e.toString()));
                if (event.getAttempts() >= maxAttempts) {
                    event.setStatus(OutboxEventEntity.Status.DEAD);
                    dead.increment();
                    try {
                        publisher.deadLetter(event);
                    } catch (RuntimeException dlqError) {
                        log.error("Could not write outbox event {} to the dead-letter queue", event.getId(), dlqError);
                    }
                }
                log.warn("Outbox publish failed for {} (attempt {})", event.getId(), event.getAttempts());
            }
            repository.save(event);
        }
    }

    private static String truncate(String value) {
        return value.length() <= 500 ? value : value.substring(0, 500);
    }
}