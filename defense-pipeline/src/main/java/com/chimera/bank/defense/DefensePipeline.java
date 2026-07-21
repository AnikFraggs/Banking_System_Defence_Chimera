package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.metrics.LayerLatencyRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;

/**
 * Runs the ordered rings of defense from outermost to innermost. The pipeline
 * short-circuits on the first terminal verdict (BLOCK / QUARANTINE) so an
 * attacker never reaches an inner layer after an outer ring has already
 * contained them. CHALLENGE is recorded and, unless later escalated, surfaced
 * to the caller as a step-up requirement.
 *
 * <p>Every ring's verdict is retained in the result for a full audit trail.
 */
@Component
public class DefensePipeline {

    private static final Logger log = LoggerFactory.getLogger(DefensePipeline.class);

    private final List<DefenseLayer> layers;
    private final LayerLatencyRegistry latency;

    public DefensePipeline(List<DefenseLayer> layers) {
        this(layers, null);
    }

    @Autowired
    public DefensePipeline(List<DefenseLayer> layers, LayerLatencyRegistry latency) {
        this.layers = layers.stream()
                .sorted(Comparator.comparingInt(DefenseLayer::order))
                .toList();
        this.latency = latency;
    }

    public DefenseResult evaluate(DefenseContext context) {
        DefenseResult result = new DefenseResult(context.correlationId());
        LayerVerdict strongest = LayerVerdict.pass("pipeline");

        for (DefenseLayer layer : layers) {
            LayerVerdict verdict;
            long startNanos = System.nanoTime();
            try {
                verdict = layer.inspect(context);
            } catch (RuntimeException ex) {
                // A layer failure must fail safe: treat as a challenge, never an implicit pass.
                log.warn("Layer {} threw ({}); failing safe to CHALLENGE.", layer.name(), ex.toString());
                verdict = LayerVerdict.challenge(layer.name(), "layer_error_fail_safe", 0.5);
            }
            long micros = (System.nanoTime() - startNanos) / 1000;
            result.recordLatency(layer.name(), micros);
            if (latency != null) {
                latency.record(layer.name(), micros);
            }
            result.record(verdict);

            if (verdict.decision().rank() > strongest.decision().rank()) {
                strongest = verdict;
            }
            if (verdict.isTerminal()) {
                log.info("Pipeline halted at layer '{}' with {} for {}",
                        layer.name(), verdict.decision(), context.correlationId());
                break;
            }
        }

        result.setFinalVerdict(strongest);
        return result;
    }
}
