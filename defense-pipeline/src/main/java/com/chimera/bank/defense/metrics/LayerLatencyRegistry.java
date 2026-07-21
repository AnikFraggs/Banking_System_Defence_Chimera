package com.chimera.bank.defense.metrics;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Thread-safe accumulator of per-layer inspection latency.
 *
 * <p>The pipeline records how long each ring's {@code inspect()} takes (in
 * microseconds); this registry aggregates those samples so the health surface
 * can report p50 / p95 / max / mean and a call count per layer. A slow ring is
 * both a performance and a security signal (e.g. a ReDoS-y pattern, or a stalled
 * downstream call), so it is surfaced on the manager dashboard.
 *
 * <p>Samples are kept in a bounded ring buffer per layer so memory stays flat
 * under sustained load; percentiles are computed over the retained window.
 */
@Component
public class LayerLatencyRegistry {

    /** Retained samples per layer for percentile estimation. */
    private static final int WINDOW = 1024;

    private final Map<String, Window> byLayer = new ConcurrentHashMap<>();

    public record LatencyStats(
            String layer, long count, double meanMicros,
            double p50Micros, double p95Micros, double maxMicros) {
    }

    /** Record one inspection latency sample for {@code layer}, in microseconds. */
    public void record(String layer, long micros) {
        byLayer.computeIfAbsent(layer, k -> new Window()).add(micros);
    }

    /** Snapshot stats for every layer seen so far, ordered by layer name. */
    public Map<String, LatencyStats> snapshot() {
        Map<String, LatencyStats> out = new java.util.TreeMap<>();
        for (var e : byLayer.entrySet()) {
            out.put(e.getKey(), e.getValue().stats(e.getKey()));
        }
        return out;
    }

    public void reset() {
        byLayer.clear();
    }

    /** Bounded, synchronized per-layer sample window. */
    private static final class Window {
        private final long[] buf = new long[WINDOW];
        private int size = 0;
        private int next = 0;
        private long totalCount = 0;
        private double sum = 0;

        synchronized void add(long micros) {
            buf[next] = micros;
            next = (next + 1) % WINDOW;
            if (size < WINDOW) {
                size++;
            }
            totalCount++;
            sum += micros;
        }

        synchronized LatencyStats stats(String layer) {
            if (size == 0) {
                return new LatencyStats(layer, 0, 0, 0, 0, 0);
            }
            List<Long> sorted = new ArrayList<>(size);
            for (int i = 0; i < size; i++) {
                sorted.add(buf[i]);
            }
            Collections.sort(sorted);
            double p50 = percentile(sorted, 0.50);
            double p95 = percentile(sorted, 0.95);
            double max = sorted.get(sorted.size() - 1);
            double mean = sum / totalCount;
            return new LatencyStats(layer, totalCount, round1(mean),
                    round1(p50), round1(p95), round1(max));
        }

        private static double percentile(List<Long> sorted, double q) {
            if (sorted.size() == 1) {
                return sorted.get(0);
            }
            double idx = q * (sorted.size() - 1);
            int lo = (int) Math.floor(idx);
            int hi = (int) Math.ceil(idx);
            double frac = idx - lo;
            return sorted.get(lo) + frac * (sorted.get(hi) - sorted.get(lo));
        }

        private static double round1(double v) {
            return Math.round(v * 10.0) / 10.0;
        }
    }
}
