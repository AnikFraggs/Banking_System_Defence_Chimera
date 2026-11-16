package com.chimera.bank.defense.detect;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Bounded LRU of semantic-model verdicts keyed by SHA-256 of the exact input text.
 * Raw text is never retained. Only completed model inferences belong here; timeouts and
 * errors must stay uncached so a transient failure cannot become a sticky verdict.
 */
public final class SemanticVerdictCache {
    public static final int MAX_ENTRIES = 100_000;

    public record Stats(long hits, long misses, int size, int capacity) {}

    private final int capacity;
    private final Map<String, SemanticInjectionGuard.Result> entries;
    private final AtomicLong hits = new AtomicLong();
    private final AtomicLong misses = new AtomicLong();

    public SemanticVerdictCache(int capacity) {
        if (capacity < 0 || capacity > MAX_ENTRIES) {
            throw new IllegalArgumentException("Semantic cache size must be between 0 and " + MAX_ENTRIES);
        }
        this.capacity = capacity;
        this.entries = new LinkedHashMap<>(16, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, SemanticInjectionGuard.Result> eldest) {
                return size() > SemanticVerdictCache.this.capacity;
            }
        };
    }

    public static String key(String text) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is required by every Java runtime", e);
        }
    }

    public Optional<SemanticInjectionGuard.Result> get(String key) {
        if (capacity == 0) return Optional.empty();
        SemanticInjectionGuard.Result result;
        synchronized (entries) {
            result = entries.get(key);
        }
        (result == null ? misses : hits).incrementAndGet();
        return Optional.ofNullable(result);
    }

    public void put(String key, SemanticInjectionGuard.Result result) {
        if (capacity == 0) return;
        synchronized (entries) {
            entries.put(key, result);
        }
    }

    public Stats stats() {
        synchronized (entries) {
            return new Stats(hits.get(), misses.get(), entries.size(), capacity);
        }
    }
}
