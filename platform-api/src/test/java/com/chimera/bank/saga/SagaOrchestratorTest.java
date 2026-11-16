package com.chimera.bank.saga;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SagaOrchestratorTest {
    private SagaLog sagaLog;
    private SimpleMeterRegistry registry;
    private SagaOrchestrator orchestrator;
    private final UUID sagaId = UUID.randomUUID();
    private final UUID orderId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        sagaLog = mock(SagaLog.class);
        when(sagaLog.start(any(), any())).thenReturn(sagaId);
        registry = new SimpleMeterRegistry();
        orchestrator = new SagaOrchestrator(sagaLog, registry);
    }

    @Test
    void happyPathRunsStepsInOrderAndCompletes() {
        List<String> events = new ArrayList<>();
        orchestrator.execute(orderId, "SETTLEMENT", List.of(
                new SagaOrchestrator.Step("A", () -> events.add("A"), () -> events.add("compA")),
                new SagaOrchestrator.Step("B", () -> events.add("B"), () -> events.add("compB")),
                new SagaOrchestrator.Step("C", () -> events.add("C"), () -> events.add("compC"))));
        assertEquals(List.of("A", "B", "C"), events);
        verify(sagaLog).complete(sagaId);
        verify(sagaLog, never()).compensating(any(), any());
        assertEquals(1.0, registry.get("chimera_saga_completed_total").counter().count());
    }

    @Test
    void failureCompensatesCompletedStepsInReverse() {
        List<String> events = new ArrayList<>();
        RuntimeException boom = new RuntimeException("step C failed");
        RuntimeException thrown = assertThrows(RuntimeException.class, () ->
                orchestrator.execute(orderId, "SETTLEMENT", List.of(
                        new SagaOrchestrator.Step("A", () -> events.add("A"), () -> events.add("compA")),
                        new SagaOrchestrator.Step("B", () -> events.add("B"), () -> events.add("compB")),
                        new SagaOrchestrator.Step("C", () -> { events.add("C"); throw boom; }, () -> events.add("compC")))));
        assertEquals(boom, thrown);
        // C failed before its compensation was registered, so only B and A compensate, in reverse.
        assertEquals(List.of("A", "B", "C", "compB", "compA"), events);
        verify(sagaLog).compensating(eq(sagaId), any());
        verify(sagaLog).finished(sagaId, SagaInstanceEntity.Status.COMPENSATED);
        assertEquals(1.0, registry.get("chimera_saga_compensated_total").counter().count());
    }

    @Test
    void compensationFailureMarksSagaFailed() {
        List<String> events = new ArrayList<>();
        assertThrows(RuntimeException.class, () ->
                orchestrator.execute(orderId, "SETTLEMENT", List.of(
                        new SagaOrchestrator.Step("A", () -> events.add("A"),
                                () -> { throw new RuntimeException("compensation A failed"); }),
                        new SagaOrchestrator.Step("B", () -> { throw new RuntimeException("step B failed"); },
                                () -> events.add("compB")))));
        verify(sagaLog).finished(sagaId, SagaInstanceEntity.Status.FAILED);
    }
}