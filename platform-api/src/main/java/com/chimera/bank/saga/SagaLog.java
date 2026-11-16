package com.chimera.bank.saga;

import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * Durable saga log. Every write commits in its own {@code REQUIRES_NEW} transaction so the record of
 * where a workflow stopped survives even when the surrounding business transaction rolls back. The
 * step actions themselves run in the caller's transaction; only this progress log is independent.
 */
@Component
public class SagaLog {
    private final SagaInstanceRepository repository;

    public SagaLog(SagaInstanceRepository repository) {
        this.repository = repository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public UUID start(UUID orderId, String type) {
        SagaInstanceEntity saga = new SagaInstanceEntity();
        saga.setId(UUID.randomUUID());
        saga.setOrderId(orderId);
        saga.setType(type);
        saga.setStatus(SagaInstanceEntity.Status.RUNNING);
        repository.save(saga);
        return saga.getId();
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void step(UUID sagaId, String stepName) {
        repository.findById(sagaId).ifPresent(saga -> {
            saga.setCurrentStep(stepName);
            repository.save(saga);
        });
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void complete(UUID sagaId) {
        repository.findById(sagaId).ifPresent(saga -> {
            saga.setStatus(SagaInstanceEntity.Status.COMPLETED);
            repository.save(saga);
        });
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void compensating(UUID sagaId, String error) {
        repository.findById(sagaId).ifPresent(saga -> {
            saga.setStatus(SagaInstanceEntity.Status.COMPENSATING);
            saga.setLastError(truncate(error));
            repository.save(saga);
        });
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void finished(UUID sagaId, SagaInstanceEntity.Status status) {
        repository.findById(sagaId).ifPresent(saga -> {
            saga.setStatus(status);
            repository.save(saga);
        });
    }

    private static String truncate(String value) {
        if (value == null) return null;
        return value.length() <= 500 ? value : value.substring(0, 500);
    }
}