package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import com.chimera.bank.defense.vault.DeceptionVault;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * Layer 6 (pre-ultimate, innermost): deception vault redirect.
 *
 * <p>Reaching this ring means the outer layers flagged the session but the
 * platform's ML self-healing / RL controllers have not resolved it in time
 * (the caller sets {@code self_heal_failed} when its heal budget is exhausted).
 * In that case the session's sensitive working set is quarantined into the
 * isolated, manager-only {@link DeceptionVault}, protecting the real data
 * behind a boundary the hostile session can no longer reach.
 *
 * <p>If self-healing is still in progress, this layer holds with a CHALLENGE
 * (buying time) rather than quarantining prematurely.
 */
@Component
public class L6_DeceptionVaultLayer implements DefenseLayer {

    private final DeceptionVault vault;

    public L6_DeceptionVaultLayer(DeceptionVault vault) {
        this.vault = vault;
    }

    @Override
    public int order() {
        return 6;
    }

    @Override
    public String name() {
        return "L6_deception_vault";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        boolean selfHealFailed = Boolean.TRUE.equals(ctx.signals().get("self_heal_failed"));
        if (!selfHealFailed) {
            // Last-resort ring: a request that reached here without an exhausted
            // self-heal budget is not quarantined. If earlier layers flagged the
            // session, hold with a challenge to buy the self-healing controllers
            // time; otherwise the request is clean and passes.
            boolean priorSuspicion =
                    Boolean.TRUE.equals(ctx.signals().get("injection_phrasing"))
                            || Boolean.TRUE.equals(ctx.signals().get("invisible_chars"))
                            || Boolean.TRUE.equals(ctx.signals().get("homoglyph_evasion"))
                            || Boolean.TRUE.equals(ctx.signals().get("nested_encoding"))
                            || Boolean.TRUE.equals(ctx.signals().get("purpose_payload_mismatch"));
            return priorSuspicion
                    ? LayerVerdict.challenge(name(), "awaiting_self_heal", 0.5)
                    : LayerVerdict.pass(name());
        }

        Map<String, Object> snapshot = new HashMap<>(ctx.signals());
        snapshot.put("reg_no", ctx.regNo());
        snapshot.put("purpose", ctx.purpose());
        snapshot.put("received_at", ctx.receivedAt().toString());
        DeceptionVault.VaultEntry entry =
                vault.quarantine(ctx.correlationId(), "self_heal_failed_all_layers", snapshot);
        ctx.addSignal("vault_id", entry.vaultId());
        return LayerVerdict.quarantine(name(), "session_relocated_to_vault:" + entry.vaultId(), 1.0);
    }
}
