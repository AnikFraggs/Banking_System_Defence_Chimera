package com.chimera.bank.checkout;

import java.util.EnumSet;
import java.util.Map;
import java.util.Set;

public enum OrderState {
    CREATED,
    APPROVED,
    AUTHORIZED,
    SCORED,
    CAPTURED,
    STEP_UP,
    VOIDED,
    BLOCKED,
    EXPIRED;

    private static final Map<OrderState, Set<OrderState>> TRANSITIONS = Map.of(
            CREATED, EnumSet.of(APPROVED, BLOCKED, EXPIRED),
            APPROVED, EnumSet.of(AUTHORIZED),
            AUTHORIZED, EnumSet.of(SCORED),
            SCORED, EnumSet.of(CAPTURED, STEP_UP, VOIDED),
            STEP_UP, EnumSet.of(SCORED, VOIDED),
            CAPTURED, EnumSet.noneOf(OrderState.class),
            VOIDED, EnumSet.noneOf(OrderState.class),
            BLOCKED, EnumSet.noneOf(OrderState.class),
            EXPIRED, EnumSet.noneOf(OrderState.class)
    );

    public boolean canTransitionTo(OrderState next) {
        return TRANSITIONS.getOrDefault(this, Set.of()).contains(next);
    }

    public boolean terminal() {
        return this == CAPTURED || this == VOIDED || this == BLOCKED || this == EXPIRED;
    }
}
