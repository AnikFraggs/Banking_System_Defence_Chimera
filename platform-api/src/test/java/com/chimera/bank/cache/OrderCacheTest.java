package com.chimera.bank.cache;

import com.chimera.bank.checkout.CheckoutDtos;
import com.chimera.bank.checkout.OrderState;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class OrderCacheTest {
    private StringRedisTemplate redis;
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> ops = mock(ValueOperations.class);
    private SimpleMeterRegistry registry;
    private ObjectMapper mapper;
    private UUID id;
    private String key;

    @BeforeEach
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        registry = new SimpleMeterRegistry();
        mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        id = UUID.randomUUID();
        key = "checkout:order:" + id;
    }

    private OrderCache cache(boolean enabled) {
        return new OrderCache(redis, mapper, registry, enabled, 30);
    }

    private OrderCache.CachedOrder sample() {
        CheckoutDtos.OrderView view = new CheckoutDtos.OrderView(id, "PP-1", null, null, OrderState.CREATED,
                new BigDecimal("10.00"), "USD", 0.1, "CAPTURE", List.of(), null, false, false, null, false,
                Instant.now(), Instant.now());
        return new OrderCache.CachedOrder("owner", view);
    }

    @Test
    void missLoadsFromSourceAndPopulatesCache() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(key)).thenReturn(null);
        OrderCache.CachedOrder value = sample();
        OrderCache.CachedOrder result = cache(true).get(id, () -> value);
        assertEquals(value, result);
        verify(ops).set(eq(key), anyString(), eq(Duration.ofSeconds(30)));
        assertEquals(1.0, registry.get("cache.gets").tag("result", "miss").counter().count());
        assertEquals(0.0, registry.get("cache.gets").tag("result", "hit").counter().count());
    }

    @Test
    void hitSkipsLoader() throws Exception {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(key)).thenReturn(mapper.writeValueAsString(sample()));
        AtomicInteger calls = new AtomicInteger();
        OrderCache.CachedOrder result = cache(true).get(id, () -> { calls.incrementAndGet(); return sample(); });
        assertEquals(id, result.view().id());
        assertEquals("owner", result.username());
        assertEquals(0, calls.get());
        assertEquals(1.0, registry.get("cache.gets").tag("result", "hit").counter().count());
    }

    @Test
    void disabledCacheBypassesRedis() {
        AtomicInteger calls = new AtomicInteger();
        OrderCache.CachedOrder value = sample();
        OrderCache.CachedOrder result = cache(false).get(id, () -> { calls.incrementAndGet(); return value; });
        assertEquals(value, result);
        assertEquals(1, calls.get());
        verifyNoInteractions(redis);
    }

    @Test
    void redisOutageFallsThroughToLoader() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(key)).thenThrow(new RuntimeException("redis down"));
        OrderCache.CachedOrder value = sample();
        OrderCache.CachedOrder result = cache(true).get(id, () -> value);
        assertEquals(value, result);
        assertEquals(1.0, registry.get("cache.gets").tag("result", "miss").counter().count());
    }

    @Test
    void corruptEntryIsTreatedAsMiss() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(key)).thenReturn("{not-valid-json");
        OrderCache.CachedOrder value = sample();
        OrderCache.CachedOrder result = cache(true).get(id, () -> value);
        assertEquals(value, result);
        assertEquals(1.0, registry.get("cache.gets").tag("result", "miss").counter().count());
    }

    @Test
    void evictDeletesKey() {
        cache(true).evict(id);
        verify(redis).delete(key);
    }

    @Test
    void disabledEvictDoesNothing() {
        cache(false).evict(id);
        verify(redis, never()).delete(anyString());
    }
}