package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.DefenseLayer;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Set;

/**
 * Layer 2: role / status authorization (manager, accountant, customer).
 *
 * <p>Enforces that the declared purpose is permitted for the caller's role. A
 * customer attempting a manager-only action (e.g. changing health thresholds)
 * is blocked here before any deeper inspection. This is the coarse
 * "is-this-role-even-allowed-to-ask" gate; fine-grained subtree checks happen
 * in the platform-api RBAC service.
 */
@Component
public class L2_RoleStatusLayer implements DefenseLayer {

    private static final Map<Role, Set<String>> ALLOWED_PURPOSES = Map.of(
            Role.CUSTOMER, Set.of("transfer", "deposit", "withdraw", "view_own"),
            Role.ACCOUNTANT, Set.of("transfer", "deposit", "withdraw", "view_own",
                    "fraud_review", "view_customer"),
            Role.MANAGER, Set.of("transfer", "deposit", "withdraw", "view_own",
                    "fraud_review", "view_customer", "config_change", "health_admin",
                    "vault_access", "override")
    );

    @Override
    public int order() {
        return 2;
    }

    @Override
    public String name() {
        return "L2_role_status";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        Role role = ctx.role();
        String purpose = ctx.purpose();
        if (role == null) {
            return LayerVerdict.block(name(), "unknown_role", 0.9);
        }
        Set<String> allowed = ALLOWED_PURPOSES.getOrDefault(role, Set.of());
        ctx.addSignal("role", role.name());
        if (!allowed.contains(purpose)) {
            return LayerVerdict.block(name(),
                    "purpose_not_permitted_for_role:" + role + "/" + purpose, 0.85);
        }
        return LayerVerdict.pass(name());
    }
}
