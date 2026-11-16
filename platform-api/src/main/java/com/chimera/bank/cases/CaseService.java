package com.chimera.bank.cases;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

@Service
public class CaseService {
    private final CaseRepository repository;

    public CaseService(CaseRepository repository) {
        this.repository = repository;
    }

    @Transactional(readOnly = true)
    public List<CaseEntity> list() {
        return repository.findTop50ByOrderByUpdatedAtDesc();
    }

    @Transactional
    public CaseEntity open(UUID orderId) {
        return repository.findByOrderId(orderId).orElseGet(() -> {
            CaseEntity entity = new CaseEntity();
            entity.setOrderId(orderId);
            entity.setStatus("OPEN");
            return repository.save(entity);
        });
    }

    @Transactional
    public CaseEntity verdict(UUID id, String verdict) {
        CaseEntity entity = repository.findById(id).orElseThrow();
        entity.setAnalystVerdict(verdict);
        entity.setStatus("RESOLVED");
        return entity;
    }

    @Transactional
    public boolean attachExplanation(UUID orderId, String explanation) {
        return repository.findByOrderId(orderId)
                .map(entity -> {
                    entity.setExplanation(explanation);
                    return true;
                })
                .orElse(false);
    }
}
