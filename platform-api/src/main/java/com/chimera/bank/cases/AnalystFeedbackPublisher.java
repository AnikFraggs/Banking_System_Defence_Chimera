package com.chimera.bank.cases;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

@Component
public class AnalystFeedbackPublisher {
    private static final Logger log = LoggerFactory.getLogger(AnalystFeedbackPublisher.class);

    private final ObjectProvider<StringRedisTemplate> redisProvider;
    private final boolean enabled;
    private final String stream;

    public AnalystFeedbackPublisher(
            ObjectProvider<StringRedisTemplate> redisProvider,
            @Value("${chimera.cases.feedback.enabled:false}") boolean enabled,
            @Value("${chimera.cases.feedback.stream:fraud-gate:analyst-verdicts}") String stream) {
        this.redisProvider = redisProvider;
        this.enabled = enabled;
        this.stream = stream;
    }

    public void publish(CaseEntity entity) {
        if (!enabled) return;
        try {
            Map<String, String> event = new LinkedHashMap<>();
            event.put("case_id", entity.getId().toString());
            event.put("order_id", entity.getOrderId().toString());
            event.put("verdict", entity.getAnalystVerdict());
            event.put("analysis", entity.getExplanation() == null ? "" : entity.getExplanation());
            StringRedisTemplate redis = redisProvider.getObject();
            redis.opsForStream().add(stream, event);
        } catch (RuntimeException error) {
            log.warn("Analyst verdict persisted but feedback publishing failed for case {}", entity.getId(), error);
        }
    }
}
