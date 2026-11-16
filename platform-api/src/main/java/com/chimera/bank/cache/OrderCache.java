package com.chimera.bank.cache;

import com.chimera.bank.checkout.CheckoutDtos;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * Cache-aside for checkout order reads. Reads populate Redis on miss; every write path evicts the
 * key so a stale order is never served. Hit/miss counters expose the cache hit ratio to Prometheus.
 * Only the non-secret read view (no demo OTP) is cached.
 */
@Component
public class OrderCache {
    private static final String PREFIX = "checkout:order:";

    /** The owner is cached with the view so a cache hit can still be authorization-checked. */
    public record CachedOrder(String username, CheckoutDtos.OrderView view) {}

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final Counter hits;
    private final Counter misses;
    private final Duration ttl;
    private final boolean enabled;

    public OrderCache(StringRedisTemplate redis, ObjectMapper objectMapper, MeterRegistry registry,
                      @Value("${chimera.cache.order.enabled:true}") boolean enabled,
                      @Value("${chimera.cache.order.ttl-seconds:30}") long ttlSeconds) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.enabled = enabled;
        this.ttl = Duration.ofSeconds(ttlSeconds);
        this.hits = Counter.builder("cache.gets").tag("cache", "checkout-order").tag("result", "hit")
                .description("Checkout order cache hits").register(registry);
        this.misses = Counter.builder("cache.gets").tag("cache", "checkout-order").tag("result", "miss")
                .description("Checkout order cache misses").register(registry);
    }

    public CachedOrder get(UUID id, Supplier<CachedOrder> loader) {
        if (!enabled) return loader.get();
        String key = PREFIX + id;
        String cached = null;
        try {
            cached = redis.opsForValue().get(key);
        } catch (RuntimeException e) {
            // A cache outage must not break checkout reads; fall through to the loader.
        }
        if (cached != null) {
            try {
                CachedOrder value = objectMapper.readValue(cached, CachedOrder.class);
                hits.increment();
                return value;
            } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
                // A corrupt entry is treated as a miss and reloaded from the source of truth.
            }
        }
        misses.increment();
        CachedOrder value = loader.get();
        try {
            redis.opsForValue().set(key, objectMapper.writeValueAsString(value), ttl);
        } catch (RuntimeException | com.fasterxml.jackson.core.JsonProcessingException e) {
            // Best-effort population; the authoritative read already succeeded.
        }
        return value;
    }

    public void evict(UUID id) {
        if (!enabled) return;
        try {
            redis.delete(PREFIX + id);
        } catch (RuntimeException e) {
            // Eviction is best-effort; the TTL bounds staleness if Redis is unavailable.
        }
    }
}