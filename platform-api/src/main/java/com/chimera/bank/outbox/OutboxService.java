package com.chimera.bank.outbox;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.UUID;

/**
 * Writes an outbox row in the SAME transaction as the business change, so an event is never lost
 * even if the process crashes after commit. A separate relay publishes committed rows to the
 * broker (Redis stream by default, Kafka when enabled) — at-least-once delivery.
 */
@Service
public class OutboxService {
    private final OutboxEventRepository repository;
    private final ObjectMapper objectMapper;
    private final Counter recorded;

    public OutboxService(OutboxEventRepository repository, ObjectMapper objectMapper, MeterRegistry registry) {
        this.repository = repository;
        this.objectMapper = objectMapper;
        this.recorded = Counter.builder("chimera_outbox_recorded_total")
                .description("Outbox events written transactionally with business changes").register(registry);
    }

    @Transactional(propagation = Propagation.REQUIRED)
    public void record(String aggregateType, UUID aggregateId, String eventType, Map<String, ?> details) {
        try {
            OutboxEventEntity event = new OutboxEventEntity();
            event.setAggregateType(aggregateType);
            event.setAggregateId(aggregateId);
            event.setEventType(eventType);
            event.setPayload(objectMapper.writeValueAsString(details));
            event.setStatus(OutboxEventEntity.Status.NEW);
            repository.save(event);
            recorded.increment();
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("Could not serialize outbox event", e);
        }
    }
}