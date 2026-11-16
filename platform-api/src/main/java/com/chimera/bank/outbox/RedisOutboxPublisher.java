package com.chimera.bank.outbox;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;

/** Default outbox transport: Redis Streams. No Kafka broker is required for local use. */
@Component
@ConditionalOnProperty(name = "chimera.outbox.kafka.enabled", havingValue = "false", matchIfMissing = true)
public class RedisOutboxPublisher implements OutboxPublisher {
    private final StringRedisTemplate redis;
    private final String stream;
    private final String dlqStream;

    public RedisOutboxPublisher(StringRedisTemplate redis,
                                @org.springframework.beans.factory.annotation.Value("${chimera.outbox.stream:chimera:outbox}") String stream,
                                @org.springframework.beans.factory.annotation.Value("${chimera.outbox.dlq-stream:chimera:outbox:dlq}") String dlqStream) {
        this.redis = redis;
        this.stream = stream;
        this.dlqStream = dlqStream;
    }

    @Override
    public void publish(OutboxEventEntity event) {
        redis.opsForStream().add(record(stream, event));
    }

    @Override
    public void deadLetter(OutboxEventEntity event) {
        redis.opsForStream().add(record(dlqStream, event));
    }

    private MapRecord<String, String, String> record(String target, OutboxEventEntity event) {
        return StreamRecords.string(Map.of(
                "id", event.getId().toString(),
                "aggregateType", event.getAggregateType(),
                "aggregateId", event.getAggregateId().toString(),
                "eventType", event.getEventType(),
                "payload", event.getPayload())).withStreamKey(target);
    }
}