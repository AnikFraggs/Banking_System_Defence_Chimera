package com.chimera.bank.outbox;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OutboxRelayTest {
    private OutboxEventRepository repository;
    private OutboxPublisher publisher;
    private SimpleMeterRegistry registry;

    @BeforeEach
    void setUp() {
        repository = mock(OutboxEventRepository.class);
        publisher = mock(OutboxPublisher.class);
        registry = new SimpleMeterRegistry();
    }

    private OutboxRelay relay(int maxAttempts) {
        return new OutboxRelay(repository, publisher, registry, maxAttempts);
    }

    private OutboxEventEntity newEvent() {
        OutboxEventEntity event = new OutboxEventEntity();
        event.setId(UUID.randomUUID());
        event.setAggregateType("CheckoutOrder");
        event.setAggregateId(UUID.randomUUID());
        event.setEventType("ORDER_CAPTURED");
        event.setPayload("{}");
        event.setStatus(OutboxEventEntity.Status.NEW);
        return event;
    }

    @Test
    void successfulPublishMarksPublished() {
        OutboxEventEntity event = newEvent();
        when(repository.findTop50ByStatusOrderByCreatedAtAsc(OutboxEventEntity.Status.NEW)).thenReturn(List.of(event));
        relay(5).relay();
        assertEquals(OutboxEventEntity.Status.PUBLISHED, event.getStatus());
        assertNotNull(event.getPublishedAt());
        verify(publisher).publish(event);
        verify(publisher, never()).deadLetter(any());
        assertEquals(1.0, registry.get("chimera_outbox_published_total").counter().count());
    }

    @Test
    void failedPublishRetriesThenDeadLetters() {
        OutboxEventEntity event = newEvent();
        when(repository.findTop50ByStatusOrderByCreatedAtAsc(OutboxEventEntity.Status.NEW)).thenReturn(List.of(event));
        doThrow(new RuntimeException("broker down")).when(publisher).publish(any());
        OutboxRelay relay = relay(2);

        relay.relay();
        assertEquals(1, event.getAttempts());
        assertEquals(OutboxEventEntity.Status.NEW, event.getStatus());
        verify(publisher, never()).deadLetter(any());

        relay.relay();
        assertEquals(2, event.getAttempts());
        assertEquals(OutboxEventEntity.Status.DEAD, event.getStatus());
        verify(publisher).deadLetter(event);
        assertEquals(1.0, registry.get("chimera_outbox_dead_total").counter().count());
    }

    @Test
    void deadLetterFailureStillMarksDead() {
        OutboxEventEntity event = newEvent();
        when(repository.findTop50ByStatusOrderByCreatedAtAsc(OutboxEventEntity.Status.NEW)).thenReturn(List.of(event));
        doThrow(new RuntimeException("broker down")).when(publisher).publish(any());
        doThrow(new RuntimeException("dlq down")).when(publisher).deadLetter(any());
        relay(1).relay();
        assertEquals(OutboxEventEntity.Status.DEAD, event.getStatus());
        verify(repository).save(event);
    }
}