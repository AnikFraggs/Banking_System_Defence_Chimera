package com.chimera.bank.checkout;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Component
@ConditionalOnProperty(prefix = "chimera.checkout.step-up", name = "generator",
        havingValue = "deterministic", matchIfMissing = true)
public final class DeterministicVerificationChallengeGenerator implements VerificationChallengeGenerator {
    @Override
    public GeneratedChallenge generate(UUID orderId, InvoiceDiscrepancy discrepancy) {
        String prompt = "Order " + orderId + ": the simulated invoice total is " + discrepancy.currency()
                + " " + discrepancy.invoiceAmountText() + ", while the order total is " + discrepancy.currency()
                + " " + discrepancy.orderAmountText() + ". Enter the signed difference (invoice minus order), "
                + "using exactly two decimal places.";
        return new GeneratedChallenge(prompt, discrepancy.signedDifference().toPlainString());
    }
}
