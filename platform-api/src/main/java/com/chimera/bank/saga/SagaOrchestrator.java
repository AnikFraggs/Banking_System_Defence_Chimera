package com.chimera.bank.saga;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.UUID;

/**
 * A small persisted saga orchestrator. Steps run in order; if any step fails, the compensations of
 * the already-completed steps run in reverse order (compensating transactions). Progress is recorded
 * through {@link SagaLog} in independent transactions, so an operator can see exactly where a
 * distributed workflow stopped even when the business transaction rolls back.
 *
 * <p>This method is deliberately not {@code @Transactional}: the step actions participate in the
 * caller's transaction (so their writes roll back together), while only the saga log is durable.
 */
@Component
public class SagaOrchestrator {
    private static final Logger log = LoggerFactory.getLogger(SagaOrchestrator.class);

    public record Step(String name, Runnable action, Runnable compensation) {}

    private final SagaLog sagaLog;
    private final Counter completed;
    private final Counter compensated;

    public SagaOrchestrator(SagaLog sagaLog, MeterRegistry registry) {
        this.sagaLog = sagaLog;
        this.completed = Counter.builder("chimera_saga_completed_total")
                .description("Sagas that finished all steps").register(registry);
        this.compensated = Counter.builder("chimera_saga_compensated_total")
                .description("Sagas that rolled back via compensating transactions").register(registry);
    }

    public void execute(UUID orderId, String type, List<Step> steps) {
        UUID sagaId = sagaLog.start(orderId, type);
        Deque<Runnable> compensations = new ArrayDeque<>();
        try {
            for (Step step : steps) {
                sagaLog.step(sagaId, step.name());
                step.action().run();
                compensations.push(step.compensation());
            }
            sagaLog.complete(sagaId);
            completed.increment();
        } catch (RuntimeException e) {
            sagaLog.compensating(sagaId, e.toString());
            boolean compensationFailed = false;
            while (!compensations.isEmpty()) {
                try {
                    compensations.pop().run();
                } catch (RuntimeException compensationError) {
                    compensationFailed = true;
                    log.error("Saga {} compensation failed for order {}", sagaId, orderId, compensationError);
                }
            }
            sagaLog.finished(sagaId, compensationFailed
                    ? SagaInstanceEntity.Status.FAILED : SagaInstanceEntity.Status.COMPENSATED);
            compensated.increment();
            throw e;
        }
    }
}