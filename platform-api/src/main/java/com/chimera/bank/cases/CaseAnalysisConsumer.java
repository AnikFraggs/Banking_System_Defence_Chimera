package com.chimera.bank.cases;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Component
@ConditionalOnProperty(name = "chimera.cases.async-results.enabled", havingValue = "true")
public class CaseAnalysisConsumer {
    private static final Logger log = LoggerFactory.getLogger(CaseAnalysisConsumer.class);

    private final StringRedisTemplate redis;
    private final CaseService cases;
    private final ObjectMapper objectMapper;
    private final String stream;
    private final String group;
    private final String consumer;

    public CaseAnalysisConsumer(
            StringRedisTemplate redis,
            CaseService cases,
            ObjectMapper objectMapper,
            @Value("${chimera.cases.async-results.stream:fraud-gate:explanations:results}") String stream,
            @Value("${chimera.cases.async-results.group:platform-api-analyst-cases}") String group,
            @Value("${chimera.cases.async-results.consumer:platform-api-local}") String consumer) {
        this.redis = redis;
        this.cases = cases;
        this.objectMapper = objectMapper;
        this.stream = stream;
        this.group = group;
        this.consumer = consumer;
    }

    @PostConstruct
    void createGroup() {
        try {
            redis.opsForStream().createGroup(stream, ReadOffset.from("0"), group);
        } catch (RuntimeException error) {
            log.info("Case-analysis consumer group was not created; it may already exist", error);
        }
    }

    @Scheduled(fixedDelayString = "${chimera.cases.async-results.poll-ms:1000}")
    void poll() {
        try {
            process(read(ReadOffset.from("0")));
            process(read(ReadOffset.lastConsumed()));
        } catch (RuntimeException error) {
            log.warn("Unable to consume asynchronous case analysis", error);
        }
    }

    private List<MapRecord<String, Object, Object>> read(ReadOffset offset) {
        List<MapRecord<String, Object, Object>> records = redis.opsForStream().read(
                Consumer.from(group, consumer),
                StreamReadOptions.empty().count(20),
                StreamOffset.create(stream, offset));
        return records == null ? List.of() : records;
    }

    private void process(List<MapRecord<String, Object, Object>> records) {
        for (MapRecord<String, Object, Object> record : records) {
                UUID orderId;
                String analysis;
                try {
                    Map<String, Object> values = new LinkedHashMap<>();
                    record.getValue().forEach((key, value) -> values.put(String.valueOf(key), value));
                    Object payload = values.get("payload");
                    if (payload instanceof String json) {
                        values.putAll(objectMapper.readValue(json, Map.class));
                    }
                    orderId = UUID.fromString(String.valueOf(values.get("order_id")));
                    analysis = objectMapper.writeValueAsString(values);
                } catch (Exception error) {
                    log.warn("Discarding malformed asynchronous case analysis {}", record.getId(), error);
                    redis.opsForStream().acknowledge(stream, group, record.getId());
                    continue;
                }
                if (cases.attachExplanation(orderId, analysis)) {
                    redis.opsForStream().acknowledge(stream, group, record.getId());
                }
        }
    }
}
