package com.chimera.bank.checkout;

import java.util.UUID;

/** Generates the contextual L5 prompt and private answer; never called pre-capture. */
public interface VerificationChallengeGenerator {
    record GeneratedChallenge(String prompt, String expectedAnswer) {}

    GeneratedChallenge generate(UUID orderId, InvoiceDiscrepancy discrepancy);
}
