package com.chimera.bank.health;

import com.chimera.bank.ai.AiBrainClient;
import com.chimera.bank.defense.DefenseLayer;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Computes a real, quantitative platform health score from live component
 * readiness — it does NOT fabricate status via a try/get on random values.
 *
 * <p>Each contributing subsystem reports a boolean/graded readiness; the score
 * is a weighted aggregate in [0,100] with an explicit breakdown so a manager
 * can see exactly which subsystem degraded and why.
 */
@Service
public class HealthScoreService {

    private final AiBrainClient aiBrain;
    private final List<DefenseLayer> layers;

    public HealthScoreService(AiBrainClient aiBrain, List<DefenseLayer> layers) {
        this.aiBrain = aiBrain;
        this.layers = layers;
    }

    public record ComponentHealth(String component, boolean ready, double weight, String detail) {
    }

    public record HealthReport(String status, double score, List<ComponentHealth> components) {
    }

    public HealthReport compute() {
        boolean brainUp = aiBrain.brainHealthy();
        boolean layersLoaded = layers.size() >= 6;

        List<ComponentHealth> components = List.of(
                new ComponentHealth("defense_pipeline", layersLoaded, 0.40,
                        layers.size() + " layers active"),
                new ComponentHealth("ai_brain", brainUp, 0.35,
                        brainUp ? "reachable" : "unreachable (fallback active)"),
                new ComponentHealth("api", true, 0.25, "serving")
        );

        double score = 0.0;
        double totalWeight = 0.0;
        for (ComponentHealth c : components) {
            totalWeight += c.weight();
            if (c.ready()) {
                score += c.weight();
            }
        }
        double pct = totalWeight == 0 ? 0 : (score / totalWeight) * 100.0;

        String status;
        if (pct >= 90) {
            status = "healthy";
        } else if (pct >= 60) {
            status = "degraded";
        } else {
            status = "critical";
        }
        return new HealthReport(status, Math.round(pct * 10.0) / 10.0, components);
    }

    /** Sorted layer roster for the manager dashboard. */
    public Map<Integer, String> layerRoster() {
        Map<Integer, String> roster = new TreeMap<>();
        for (DefenseLayer l : layers) {
            roster.put(l.order(), l.name());
        }
        return roster;
    }
}
