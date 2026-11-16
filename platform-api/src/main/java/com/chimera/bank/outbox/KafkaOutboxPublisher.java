package com.chimera.bank.outbox;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Component;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Optional Kafka transport for the transactional outbox. Enabled only when a broker is configured. */
@Component
@ConditionalOnProperty(name = "chimera.outbox.kafka.enabled", havingValue = "true")
public class KafkaOutboxPublisher implements OutboxPublisher {
    private static final long SEND_TIMEOUT_SECONDS = 10;

    private final KafkaTemplate<String, String> kafka;
    private final String topic;
    private final String dlqTopic;

    public KafkaOutboxPublisher(KafkaTemplate<String, String> kafka,
                                @Value("${chimera.outbox.kafka.topic:chimera.outbox}") String topic,
                                @Value("${chimera.outbox.kafka.dlq-topic:chimera.outbox.dlq}") String dlqTopic) {
        this.kafka = kafka;
        this.topic = topic;
        this.dlqTopic = dlqTopic;
    }

    @Override
    public void publish(OutboxEventEntity event) {
        sendAndWait(topic, event);
    }

    @Override
    public void deadLetter(OutboxEventEntity event) {
        sendAndWait(dlqTopic, event);
    }

    private void sendAndWait(String topic, OutboxEventEntity event) {
        String key = event.getAggregateId().toString();
        String payload = event.getPayload();
        try {
            java.util.concurrent.CompletableFuture<SendResult<String, String>> future =
                    kafka.send(topic, key, payload);
            SendResult<String, String> result = future.get(SEND_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (result.getRecordMetadata() == null) {
                throw new IllegalStateException("Kafka send returned null record metadata for topic=" + topic + " key=" + key);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Kafka send interrupted for topic=" + topic + " key=" + key, e);
        } catch (ExecutionException e) {
            throw new IllegalStateException("Kafka send failed for topic=" + topic + " key=" + key, e.getCause());
        } catch (TimeoutException e) {
            throw new IllegalStateException("Kafka send timed out after " + SEND_TIMEOUT_SECONDS + "s for topic=" + topic + " key=" + key, e);
        }
    }
}