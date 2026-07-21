package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import org.springframework.stereotype.Component;

import java.util.Set;

/**
 * Layer 3: purpose coherence.
 *
 * <p>Checks that the declared purpose is a known operation and that the request
 * payload is consistent with it (e.g. a "withdraw" purpose should not carry
 * beneficiary-account fields typical of a "transfer"). Mismatch between stated
 * intent and payload shape is a classic sign of a replayed or tampered request,
 * so it raises a challenge rather than silently proceeding.
 */
@Component
public class L3_PurposeLayer implements DefenseLayer {

    private static final Set<String> KNOWN = Set.of(
            "transfer", "deposit", "withdraw", "view_own", "view_customer",
            "fraud_review", "config_change", "health_admin", "vault_access", "override");

    @Override
    public int order() {
        return 3;
    }

    @Override
    public String name() {
        return "L3_purpose";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        String purpose = ctx.purpose();
        if (purpose == null || !KNOWN.contains(purpose)) {
            return LayerVerdict.block(name(), "unknown_purpose:" + purpose, 0.7);
        }
        String payload = ctx.payload().toLowerCase();
        // Cheap coherence heuristics; the ML brain does the nuanced scoring later.
        boolean mentionsBeneficiary = payload.contains("beneficiary") || payload.contains("payee");
        if (purpose.equals("withdraw") && mentionsBeneficiary) {
            ctx.addSignal("purpose_payload_mismatch", true);
            return LayerVerdict.challenge(name(), "withdraw_with_beneficiary_fields", 0.55);
        }
        ctx.addSignal("purpose_validated", purpose);
        return LayerVerdict.pass(name());
    }
}
