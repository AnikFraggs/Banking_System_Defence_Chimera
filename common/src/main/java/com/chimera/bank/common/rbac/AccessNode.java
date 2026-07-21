package com.chimera.bank.common.rbac;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

/**
 * A node in the bank's access tree. Each node carries a registration number
 * (captured at sign-up), a role tier, and its home branch. Managers sit at the
 * root with full reach over their subtree; accountants supervise a set of
 * customers; customers are leaves with access only to their own resources.
 *
 * <p>This models the "tree node system classified under customer / accountant /
 * manager" requested: authority flows down the tree, and a node can only act on
 * targets inside its own subtree.
 */
public final class AccessNode {

    private final String regNo;
    private final Role role;
    private final String branchCode;
    private AccessNode parent;
    private final List<AccessNode> children = new ArrayList<>();

    public AccessNode(String regNo, Role role, String branchCode) {
        this.regNo = regNo;
        this.role = role;
        this.branchCode = branchCode;
    }

    public AccessNode addChild(AccessNode child) {
        // A child must be strictly lower clearance than its parent, except that
        // a MANAGER may nest sub-branches led by another MANAGER.
        boolean managerNesting = this.role == Role.MANAGER && child.role == Role.MANAGER;
        if (!managerNesting && this.role.clearance() <= child.role.clearance()) {
            throw new IllegalArgumentException(
                    "Child role " + child.role + " must be lower clearance than parent " + this.role);
        }
        child.parent = this;
        this.children.add(child);
        return child;
    }

    /** True if {@code target} is this node or lives anywhere in this node's subtree. */
    public boolean canReach(AccessNode target) {
        if (target == null) {
            return false;
        }
        for (AccessNode n = target; n != null; n = n.parent) {
            if (n == this) {
                return true;
            }
        }
        return false;
    }

    /** True if this node may act on the target: sufficient clearance AND in-subtree (or self). */
    public boolean mayActOn(AccessNode target) {
        if (this == target) {
            return true;
        }
        return this.role.dominates(target.role) && canReach(target);
    }

    public Optional<AccessNode> findByRegNo(String targetRegNo) {
        if (this.regNo.equals(targetRegNo)) {
            return Optional.of(this);
        }
        for (AccessNode child : children) {
            Optional<AccessNode> found = child.findByRegNo(targetRegNo);
            if (found.isPresent()) {
                return found;
            }
        }
        return Optional.empty();
    }

    public String regNo() {
        return regNo;
    }

    public Role role() {
        return role;
    }

    public String branchCode() {
        return branchCode;
    }

    public AccessNode parent() {
        return parent;
    }

    public List<AccessNode> children() {
        return Collections.unmodifiableList(children);
    }

    @Override
    public String toString() {
        return "AccessNode{regNo=%s, role=%s, branch=%s, children=%d}"
                .formatted(regNo, role, branchCode, children.size());
    }
}
