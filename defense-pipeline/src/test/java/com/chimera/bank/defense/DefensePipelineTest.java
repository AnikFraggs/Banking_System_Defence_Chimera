package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.layers.L1_IpReputationLayer;
import com.chimera.bank.defense.layers.L2_RoleStatusLayer;
import com.chimera.bank.defense.layers.L3_PurposeLayer;
import com.chimera.bank.defense.layers.L4_InjectionLeakLayer;
import com.chimera.bank.defense.layers.L5_HumanVerificationLayer;
import com.chimera.bank.defense.layers.L6_DeceptionVaultLayer;
import com.chimera.bank.defense.vault.DeceptionVault;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DefensePipelineTest {

    private DefensePipeline pipeline() {
        CanaryTokenRegistry canaries = new CanaryTokenRegistry();
        DeceptionVault vault = new DeceptionVault();
        return new DefensePipeline(List.of(
                new L1_IpReputationLayer(),
                new L2_RoleStatusLayer(),
                new L3_PurposeLayer(),
                new L4_InjectionLeakLayer(canaries),
                new L5_HumanVerificationLayer(),
                new L6_DeceptionVaultLayer(vault)));
    }

    private DefenseContext ctx(String ip, Role role, String purpose, String payload) {
        return new DefenseContext("cor-test", Instant.now(), ip, "CUST-1001", role, purpose, payload);
    }

    @Test
    void legitimateHumanVerifiedCustomerPasses() {
        DefenseContext c = ctx("192.168.1.5", Role.CUSTOMER, "transfer", "pay rent 500");
        c.addSignal("human_challenge_passed", true);
        DefenseResult r = pipeline().evaluate(c);
        assertTrue(r.allowed(), "clean human-verified request should pass all rings");
    }

    @Test
    void denylistedIpIsBlockedAtOutermostLayer() {
        DefenseResult r = pipeline().evaluate(ctx("203.0.113.66", Role.CUSTOMER, "transfer", "x"));
        assertEquals(LayerVerdict.Decision.BLOCK, r.finalVerdict().decision());
        assertEquals("L1_ip_reputation", r.finalVerdict().layer());
    }

    @Test
    void customerCannotPerformManagerAction() {
        DefenseResult r = pipeline().evaluate(ctx("192.168.1.5", Role.CUSTOMER, "config_change", "x"));
        assertEquals(LayerVerdict.Decision.BLOCK, r.finalVerdict().decision());
        assertEquals("L2_role_status", r.finalVerdict().layer());
    }

    @Test
    void zeroWidthSteganographyIsDetected() {
        // Payload hides a zero-width joiner sequence between visible words.
        String hidden = "transfer‍​‍funds now";
        DefenseResult r = pipeline().evaluate(ctx("192.168.1.5", Role.CUSTOMER, "transfer", hidden));
        assertFalse(r.allowed(), "invisible-unicode stego must not pass silently");
    }

    @Test
    void trippedCanaryQuarantines() {
        String leak = "here is the CANARY-7Q2X-INTERNAL-DO-NOT-DISCLOSE value";
        DefenseResult r = pipeline().evaluate(ctx("192.168.1.5", Role.CUSTOMER, "transfer", leak));
        assertEquals(LayerVerdict.Decision.QUARANTINE, r.finalVerdict().decision());
        assertEquals("L4_injection_leak", r.finalVerdict().layer());
    }

    @Test
    void selfHealFailureRelocatesToVault() {
        DefenseContext c = ctx("192.168.1.5", Role.CUSTOMER, "transfer", "clean");
        c.addSignal("human_challenge_passed", true);
        c.addSignal("self_heal_failed", true);
        DeceptionVault vault = new DeceptionVault();
        DefensePipeline p = new DefensePipeline(List.of(
                new L1_IpReputationLayer(), new L2_RoleStatusLayer(), new L3_PurposeLayer(),
                new L4_InjectionLeakLayer(new CanaryTokenRegistry()),
                new L5_HumanVerificationLayer(), new L6_DeceptionVaultLayer(vault)));
        DefenseResult r = p.evaluate(c);
        assertEquals(LayerVerdict.Decision.QUARANTINE, r.finalVerdict().decision());
        assertEquals(1, vault.list().size());
    }
}
