package com.chimera.bank.defense;

import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.healing.HealingRag;
import com.chimera.bank.defense.healing.SelfHealingController;
import com.chimera.bank.defense.layers.L1_IpReputationLayer;
import com.chimera.bank.defense.layers.L2_RoleStatusLayer;
import com.chimera.bank.defense.layers.L3_PurposeLayer;
import com.chimera.bank.defense.layers.L4_InjectionLeakLayer;
import com.chimera.bank.defense.layers.L5_HumanVerificationLayer;
import com.chimera.bank.defense.layers.L6_DeceptionVaultLayer;
import com.chimera.bank.defense.redteam.AdversarialSample;
import com.chimera.bank.defense.redteam.AdversarialSampleGenerator;
import com.chimera.bank.defense.validation.ValidationHarness;
import com.chimera.bank.defense.validation.ValidationHarness.ValidationReport;
import com.chimera.bank.defense.vault.DeceptionVault;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Runs the 200+ deterministic adversarial battery through the full defense flow
 * and asserts the pipeline's headline health targets: high recall on real attacks,
 * decent severity calibration, and a measured RAG recovery rate. Prints the full
 * per-layer health report so it doubles as the operator's health readout.
 */
class AdversarialValidationTest {

    private DefenseOrchestrator orchestrator() {
        CanaryTokenRegistry canaries = new CanaryTokenRegistry();
        DeceptionVault vault = new DeceptionVault();
        DefensePipeline pipeline = new DefensePipeline(List.of(
                new L1_IpReputationLayer(),
                new L2_RoleStatusLayer(),
                new L3_PurposeLayer(),
                new L4_InjectionLeakLayer(canaries),
                new L5_HumanVerificationLayer(),
                new L6_DeceptionVaultLayer(vault)));
        SelfHealingController healing = new SelfHealingController(new HealingRag());
        return new DefenseOrchestrator(pipeline, healing, vault);
    }

    @Test
    void batteryHasAtLeast200Samples() {
        List<AdversarialSample> battery = AdversarialSampleGenerator.generate();
        assertTrue(battery.size() >= 200,
                "generator must produce 200+ samples, was " + battery.size());
    }

    @Test
    void validationReportMeetsHealthTargets() {
        List<AdversarialSample> battery = AdversarialSampleGenerator.generate();
        ValidationHarness harness = new ValidationHarness(orchestrator());
        ValidationReport rep = harness.run(battery);

        System.out.print(ValidationHarness.format(rep));

        // Real attacks must be caught at high recall (a missed attack is the worst outcome).
        assertTrue(rep.recall() >= 0.95,
                "recall on malicious samples should be >= 0.95, was " + rep.recall());
        // Benign traffic must not be over-blocked.
        assertTrue(rep.precision() >= 0.90,
                "precision should be >= 0.90 (low false positives), was " + rep.precision());
        // Severity predictions should correlate with ground truth.
        assertTrue(rep.pearsonR() >= 0.5,
                "severity Pearson r should be >= 0.5, was " + rep.pearsonR());
        // Every layer that saw malicious traffic should report a non-trivial health%.
        rep.perLayerHealth().values().forEach(h ->
                assertTrue(h.healthPercent() >= 0.0 && h.healthPercent() <= 100.0,
                        "health% out of range for " + h.layer()));
    }
}
