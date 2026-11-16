package com.chimera.bank.fraud;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResilientFraudGateTest {

    @SuppressWarnings("unchecked")
    private FraudGateTransport gateWith(FraudGateClient delegate) {
        ObjectProvider<GrpcFraudGateClient> grpc = mock(ObjectProvider.class);
        when(grpc.getIfAvailable()).thenReturn(null);
        ObjectProvider<FraudGateClient> http = mock(ObjectProvider.class);
        when(http.getIfAvailable()).thenReturn(delegate);
        return new ResilientFraudGateConfig().resilientFraudGate(grpc, http, new SimpleMeterRegistry());
    }

    @Test
    void circuitOpensAfterRepeatedFailClosedFallbacks() {
        FraudGateClient delegate = mock(FraudGateClient.class);
        when(delegate.score(any())).thenReturn(FraudGateFallback.challenge("GATE_TIMEOUT", "gate down", 0.0));
        FraudGateTransport gate = gateWith(delegate);

        // minimumNumberOfCalls=10, failureRateThreshold=50%: ten fail-closed results trip the breaker.
        for (int i = 0; i < 10; i++) {
            ScoreResponse response = gate.score(null);
            assertTrue(response.fallback());
            assertEquals("CHALLENGE", response.action());
        }
        ScoreResponse open = gate.score(null);
        assertEquals("GATE_CIRCUIT_OPEN", open.reasons().get(0).code());
        assertTrue(open.fallback());
        // The open circuit fast-fails without touching the delegate again.
        verify(delegate, times(10)).score(any());
    }

    @Test
    void healthyResponsesPassThroughAndKeepCircuitClosed() {
        FraudGateClient delegate = mock(FraudGateClient.class);
        ScoreResponse healthy = new ScoreResponse("d1", 0.1, "CAPTURE", java.util.List.of(),
                java.util.Map.of(), "v1", "hash", false, 12.0);
        when(delegate.score(any())).thenReturn(healthy);
        FraudGateTransport gate = gateWith(delegate);
        for (int i = 0; i < 25; i++) {
            assertEquals("CAPTURE", gate.score(null).action());
        }
        verify(delegate, times(25)).score(any());
    }

    @Test
    void requestScopedInvalidFeaturesDoNotOpenCircuit() {
        FraudGateClient delegate = mock(FraudGateClient.class);
        ScoreResponse invalidInput = new ScoreResponse("d2", 0.5, "CHALLENGE",
                java.util.List.of(new ScoreReason("INVALID_FEATURES", "no card features", "card_model", 0.5)),
                java.util.Map.of(), "v1", "hash", true, 3.0);
        when(delegate.score(any())).thenReturn(invalidInput);
        FraudGateTransport gate = gateWith(delegate);
        for (int i = 0; i < 25; i++) {
            ScoreResponse response = gate.score(null);
            assertEquals("CHALLENGE", response.action());
            assertEquals("INVALID_FEATURES", response.reasons().get(0).code());
        }
        verify(delegate, times(25)).score(any());
    }

    @Test
    void missingModelStillOpensCircuit() {
        FraudGateClient delegate = mock(FraudGateClient.class);
        ScoreResponse noModel = new ScoreResponse("d3", 0.5, "CHALLENGE",
                java.util.List.of(new ScoreReason("MODEL_UNAVAILABLE", "no model", "card_model", 0.5)),
                java.util.Map.of(), "unavailable", "hash", true, 3.0);
        when(delegate.score(any())).thenReturn(noModel);
        FraudGateTransport gate = gateWith(delegate);
        for (int i = 0; i < 10; i++) gate.score(null);
        assertEquals("GATE_CIRCUIT_OPEN", gate.score(null).reasons().get(0).code());
        verify(delegate, times(10)).score(any());
    }
}