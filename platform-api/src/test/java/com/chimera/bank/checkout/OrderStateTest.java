package com.chimera.bank.checkout;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OrderStateTest {
    @Test
    void permitsOnlyTheCheckoutStateMachine() {
        assertTrue(OrderState.CREATED.canTransitionTo(OrderState.APPROVED));
        assertTrue(OrderState.APPROVED.canTransitionTo(OrderState.AUTHORIZED));
        assertTrue(OrderState.AUTHORIZED.canTransitionTo(OrderState.SCORED));
        assertTrue(OrderState.SCORED.canTransitionTo(OrderState.CAPTURED));
        assertTrue(OrderState.SCORED.canTransitionTo(OrderState.STEP_UP));
        assertTrue(OrderState.STEP_UP.canTransitionTo(OrderState.SCORED));
        assertTrue(OrderState.SCORED.canTransitionTo(OrderState.VOIDED));
    }

    @Test
    void rejectsSkippingScoringOrSettlingTwice() {
        assertFalse(OrderState.CREATED.canTransitionTo(OrderState.CAPTURED));
        assertFalse(OrderState.APPROVED.canTransitionTo(OrderState.CAPTURED));
        assertFalse(OrderState.CAPTURED.canTransitionTo(OrderState.SCORED));
        assertFalse(OrderState.VOIDED.canTransitionTo(OrderState.CAPTURED));
        assertFalse(OrderState.BLOCKED.canTransitionTo(OrderState.CREATED));
    }
}
