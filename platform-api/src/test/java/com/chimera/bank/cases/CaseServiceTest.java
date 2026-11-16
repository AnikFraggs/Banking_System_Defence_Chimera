package com.chimera.bank.cases;

import org.junit.jupiter.api.Test;

import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CaseServiceTest {
    private final CaseRepository repository = mock(CaseRepository.class);
    private final CaseService service = new CaseService(repository);

    @Test
    void asynchronousAnalysisChangesOnlyTheExplanation() {
        UUID orderId = UUID.randomUUID();
        CaseEntity entity = new CaseEntity();
        entity.setOrderId(orderId);
        entity.setStatus("RESOLVED");
        entity.setAnalystVerdict("BENIGN");
        when(repository.findByOrderId(orderId)).thenReturn(Optional.of(entity));

        assertTrue(service.attachExplanation(orderId, "{\"judge\":\"INCONCLUSIVE\"}"));
        assertEquals("{\"judge\":\"INCONCLUSIVE\"}", entity.getExplanation());
        assertEquals("RESOLVED", entity.getStatus());
        assertEquals("BENIGN", entity.getAnalystVerdict());
    }

    @Test
    void missingCaseIsRetriedByTheStreamConsumer() {
        when(repository.findByOrderId(org.mockito.ArgumentMatchers.any())).thenReturn(Optional.empty());
        assertFalse(service.attachExplanation(UUID.randomUUID(), "analysis"));
        CaseEntity entity = new CaseEntity();
        assertNull(entity.getExplanation());
    }
}
