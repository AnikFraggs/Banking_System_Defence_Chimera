package com.chimera.bank.defense;

import com.chimera.bank.common.defense.LayerVerdict;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Full trace of a request's journey through the defense rings, plus the final verdict. */
public final class DefenseResult {

    private final String correlationId;
    private final List<LayerVerdict> trace = new ArrayList<>();
    private final Map<String, Long> layerLatencyMicros = new LinkedHashMap<>();
    private LayerVerdict finalVerdict;

    public DefenseResult(String correlationId) {
        this.correlationId = correlationId;
    }

    void record(LayerVerdict verdict) {
        trace.add(verdict);
    }

    void recordLatency(String layer, long micros) {
        layerLatencyMicros.put(layer, micros);
    }

    /** Per-layer inspection latency for THIS request, in microseconds. */
    public Map<String, Long> layerLatencyMicros() {
        return Collections.unmodifiableMap(layerLatencyMicros);
    }

    /** Total time spent across all inspected rings for this request, in microseconds. */
    public long totalLatencyMicros() {
        return layerLatencyMicros.values().stream().mapToLong(Long::longValue).sum();
    }

    void setFinalVerdict(LayerVerdict finalVerdict) {
        this.finalVerdict = finalVerdict;
    }

    public String correlationId() {
        return correlationId;
    }

    public List<LayerVerdict> trace() {
        return Collections.unmodifiableList(trace);
    }

    public LayerVerdict finalVerdict() {
        return finalVerdict;
    }

    public boolean allowed() {
        return finalVerdict != null
                && finalVerdict.decision() == LayerVerdict.Decision.PASS;
    }
}
