package com.chimera.bank.outbox;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class KafkaOutboxPublisherTest {

    private KafkaTemplate<String, String> kafkaTemplate;
    private KafkaOutboxPublisher publisher;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        kafkaTemplate = mock(KafkaTemplate.class);
        publisher = new KafkaOutboxPublisher(kafkaTemplate, "chimera.outbox", "chimera.outbox.dlq", 1);
    }

    private OutboxEventEntity createTestEvent() {
        OutboxEventEntity event = new OutboxEventEntity();
        event.setId(UUID.randomUUID());
        event.setAggregateType("Order");
        event.setAggregateId(UUID.randomUUID());
        event.setEventType("ORDER_CREATED");
        event.setPayload("{\"amount\":100}");
        event.setStatus(OutboxEventEntity.Status.NEW);
        return event;
    }

    @Test
    void publishSucceedsWhenKafkaCompletes() {
        OutboxEventEntity event = createTestEvent();
        CompletableFuture<SendResult<String, String>> future = CompletableFuture.completedFuture(null);
        when(kafkaTemplate.send(eq("chimera.outbox"), eq(event.getAggregateId().toString()), eq(event.getPayload())))
                .thenReturn(future);

        assertDoesNotThrow(() -> publisher.publish(event));
        verify(kafkaTemplate).send("chimera.outbox", event.getAggregateId().toString(), event.getPayload());
    }

    @Test
    void publishThrowsOnKafkaFailureLeavingRowPending() {
        OutboxEventEntity event = createTestEvent();
        CompletableFuture<SendResult<String, String>> failedFuture = new CompletableFuture<>();
        failedFuture.completeExceptionally(new TimeoutException("Kafka broker unreachable"));
        when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(failedFuture);

        RuntimeException ex = assertThrows(RuntimeException.class, () -> publisher.publish(event));
        assertTrue(ex.getMessage().contains("Kafka send failed") || ex.getMessage().contains("Kafka outbox publish failed"));
    }

    @Test
    void outboxAckFailureThrowsAndLeavesRowPendingForRetry() {
        OutboxEventEntity event = createTestEvent();
        CompletableFuture<SendResult<String, String>> unackedFuture = new CompletableFuture<>();
        unackedFuture.completeExceptionally(new org.apache.kafka.common.errors.NotLeaderOrFollowerException("Broker rejected write: ack failure"));
        when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(unackedFuture);

        RuntimeException ex = assertThrows(RuntimeException.class, () -> publisher.publish(event));
        assertTrue(ex.getMessage().contains("Kafka send failed"));
        assertEquals(OutboxEventEntity.Status.NEW, event.getStatus(), "Row remains in NEW/PENDING status when ACK fails");
    }

    @Test
    void markPendingForRetryFallbackLogsAndThrows() {
        OutboxEventEntity event = createTestEvent();
        RuntimeException ex = assertThrows(RuntimeException.class, () ->
                publisher.markPendingForRetry(event, new RuntimeException("Kafka timeout")));

        assertTrue(ex.getMessage().contains("leaving row PENDING"));
    }

    @Test
    void deadLetterPublishesToDlqTopic() {
        OutboxEventEntity event = createTestEvent();
        CompletableFuture<SendResult<String, String>> future = CompletableFuture.completedFuture(null);
        when(kafkaTemplate.send(eq("chimera.outbox.dlq"), eq(event.getAggregateId().toString()), eq(event.getPayload())))
                .thenReturn(future);

        assertDoesNotThrow(() -> publisher.deadLetter(event));
        verify(kafkaTemplate).send("chimera.outbox.dlq", event.getAggregateId().toString(), event.getPayload());
    }
}
