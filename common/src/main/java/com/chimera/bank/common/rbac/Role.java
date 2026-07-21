package com.chimera.bank.common.rbac;

/**
 * Access tiers in the RBAC tree. Ordinal encodes privilege height so a parent
 * node's clearance dominates its children:
 *
 * <pre>
 *              MANAGER            (full access: config, health, overrides)
 *             /       \
 *      ACCOUNTANT   ACCOUNTANT    (mid: transactions, fraud review, no config)
 *        /    \        /    \
 *   CUSTOMER ...    CUSTOMER ...  (least: own account, own transactions)
 * </pre>
 *
 * Clearance is compared numerically; a node may act on a target only when its
 * clearance is greater-or-equal AND the target is within its subtree.
 */
public enum Role {
    CUSTOMER(0),
    ACCOUNTANT(1),
    MANAGER(2);

    private final int clearance;

    Role(int clearance) {
        this.clearance = clearance;
    }

    public int clearance() {
        return clearance;
    }

    public boolean dominates(Role other) {
        return this.clearance >= other.clearance;
    }
}
