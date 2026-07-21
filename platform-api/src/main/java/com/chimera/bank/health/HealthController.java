package com.chimera.bank.health;

import com.chimera.bank.defense.metrics.LayerLatencyRegistry;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Health surface. The score is computed from live component readiness by
 * {@link HealthScoreService} (no synthetic/random status). Managers get the
 * full breakdown, layer roster, and per-layer latency; the plain readiness is
 * public.
 */
@RestController
@RequestMapping("/api/health")
public class HealthController {

    private final HealthScoreService healthService;
    private final LayerLatencyRegistry latency;

    public HealthController(HealthScoreService healthService, LayerLatencyRegistry latency) {
        this.healthService = healthService;
        this.latency = latency;
    }

    @GetMapping
    public HealthScoreService.HealthReport health() {
        return healthService.compute();
    }

    @GetMapping("/layers")
    public Map<Integer, String> layers() {
        return healthService.layerRoster();
    }

    /** Per-layer inspection latency (p50/p95/max/mean, in microseconds). */
    @GetMapping("/latency")
    public Map<String, LayerLatencyRegistry.LatencyStats> latency() {
        return latency.snapshot();
    }
}
