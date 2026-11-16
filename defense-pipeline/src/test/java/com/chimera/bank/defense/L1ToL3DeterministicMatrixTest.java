package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.defense.LayerVerdict.Decision;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.layers.L1_IpReputationLayer;
import com.chimera.bank.defense.layers.L2_RoleStatusLayer;
import com.chimera.bank.defense.layers.L3_PurposeLayer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.MethodSource;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Exhaustive deterministic matrix for the rule-based outer rings (no models involved). */
class L1ToL3DeterministicMatrixTest {

    private static final List<String> KNOWN_PURPOSES = List.of(
            "transfer", "deposit", "withdraw", "view_own", "view_customer", "fraud_review", "config_change",
            "health_admin", "vault_access", "override", "checkout", "manager_override");

    private static final Map<Role, Set<String>> EXPECTED_ALLOWED = Map.of(
            Role.CUSTOMER, Set.of("transfer", "deposit", "withdraw", "view_own", "checkout"),
            Role.ACCOUNTANT, Set.of("transfer", "deposit", "withdraw", "view_own", "checkout",
                    "fraud_review", "view_customer"),
            Role.MANAGER, Set.copyOf(KNOWN_PURPOSES));

    private static DefenseContext ctx(String ip, Role role, String purpose, String payload) {
        return new DefenseContext("cor-matrix", Instant.EPOCH, ip, "CUST-1001", role, purpose, payload);
    }

    @ParameterizedTest(name = "L1 ip=''{0}'' -> {1}")
    @CsvSource(value = {
            "NULL, CHALLENGE, missing_source_ip",
            "'', CHALLENGE, missing_source_ip",
            "'   ', CHALLENGE, missing_source_ip",
            "203.0.113.66, BLOCK, denylisted_source_ip",
            "0.0.0.0, BLOCK, denylisted_source_ip",
            "192.168.1.5, PASS, ",
            "10.0.0.7, PASS, ",
            "172.16.4.2, PASS, ",
            "8.8.8.8, PASS, ",
            "203.0.113.67, PASS, "}, nullValues = "NULL")
    void l1IpMatrix(String ip, Decision expected, String reason) {
        LayerVerdict v = new L1_IpReputationLayer().inspect(ctx(ip, Role.CUSTOMER, "transfer", "x"));
        assertEquals(expected, v.decision());
        assertEquals("L1_ip_reputation", v.layer());
        if (reason != null) {
            assertEquals(reason, v.reason());
        }
    }

    static Stream<Arguments> rolePurposeMatrix() {
        List<Arguments> out = new ArrayList<>();
        for (Role r : Role.values()) {
            for (String p : KNOWN_PURPOSES) {
                out.add(Arguments.of(r, p, EXPECTED_ALLOWED.get(r).contains(p)));
            }
            out.add(Arguments.of(r, "drop_tables", false));
            out.add(Arguments.of(r, "TRANSFER", false));
        }
        return out.stream();
    }

    @ParameterizedTest(name = "L2 {0}/{1} allowed={2}")
    @MethodSource("rolePurposeMatrix")
    void l2RolePurposeMatrix(Role role, String purpose, boolean allowed) {
        LayerVerdict v = new L2_RoleStatusLayer().inspect(ctx("192.168.1.5", role, purpose, "x"));
        assertEquals(allowed ? Decision.PASS : Decision.BLOCK, v.decision());
        if (!allowed) {
            assertEquals("purpose_not_permitted_for_role:" + role + "/" + purpose, v.reason());
        }
    }

    @Test
    void l2UnknownRoleIsBlocked() {
        LayerVerdict v = new L2_RoleStatusLayer().inspect(ctx("192.168.1.5", null, "transfer", "x"));
        assertEquals(Decision.BLOCK, v.decision());
        assertEquals("unknown_role", v.reason());
    }

    @Test
    void l2PrivilegeIsMonotoneInClearance() {
        for (Role low : Role.values()) {
            for (Role high : Role.values()) {
                if (high.dominates(low)) {
                    assertTrue(EXPECTED_ALLOWED.get(high).containsAll(EXPECTED_ALLOWED.get(low)),
                            high + " must be allowed everything " + low + " is");
                }
            }
        }
    }

    @ParameterizedTest(name = "L3 {0} + ''{1}'' -> {2}")
    @CsvSource({
            "withdraw, cash 200 at branch, PASS",
            "withdraw, send to beneficiary ACCT-1, CHALLENGE",
            "withdraw, new PAYEE please, CHALLENGE",
            "transfer, beneficiary ACCT-1 amount 50, PASS",
            "deposit, payee field present, PASS",
            "checkout, order 991, PASS",
            "teleport, x, BLOCK",
            "Transfer, x, BLOCK",
            "'', x, BLOCK"})
    void l3PurposeCoherenceMatrix(String purpose, String payload, Decision expected) {
        LayerVerdict v = new L3_PurposeLayer().inspect(ctx("192.168.1.5", Role.MANAGER, purpose, payload));
        assertEquals(expected, v.decision());
    }

    @Test
    void l3AllKnownPurposesPassWithNeutralPayload() {
        for (String p : KNOWN_PURPOSES) {
            assertEquals(Decision.PASS,
                    new L3_PurposeLayer().inspect(ctx("192.168.1.5", Role.MANAGER, p, "neutral body")).decision(), p);
        }
    }

    @Test
    void l3NullPurposeIsBlocked() {
        assertEquals(Decision.BLOCK,
                new L3_PurposeLayer().inspect(ctx("192.168.1.5", Role.MANAGER, null, "x")).decision());
    }
}
