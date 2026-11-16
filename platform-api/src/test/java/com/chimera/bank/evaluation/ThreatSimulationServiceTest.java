package com.chimera.bank.evaluation;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ThreatSimulationServiceTest {

    private final ThreatSimulationService service = new ThreatSimulationService();

    @Test
    void runAttackSimulationSqlInjectionReturnsMockBaseline() {
        ThreatSimulationService.SimulationResult result = service.runAttackSimulation("SQL_INJECTION");

        assertNotNull(result);
        assertEquals("SQL_INJECTION", result.attackType);
        assertTrue(result.detected);
        assertTrue(result.healed);
        assertTrue(result.isMock, "Threat simulation must be explicitly labeled as mock/simulated");
        assertNotNull(result.source);
        assertTrue(result.source.contains("simulated") || result.source.contains("baseline"));
        assertEquals(95.0, result.simulatedBaselineScore);
        assertEquals(95.0, result.simulatedHealingScore);
        assertEquals(95.0, result.ragScore);
    }

    @Test
    void runAttackSimulationAiBruteForceReturnsMockBaseline() {
        ThreatSimulationService.SimulationResult result = service.runAttackSimulation("AI_BRUTE_FORCE");

        assertNotNull(result);
        assertEquals("AI_BRUTE_FORCE", result.attackType);
        assertTrue(result.detected);
        assertTrue(result.healed);
        assertTrue(result.isMock);
        assertEquals(92.0, result.simulatedBaselineScore);
        assertEquals(92.0, result.simulatedHealingScore);
    }
}
