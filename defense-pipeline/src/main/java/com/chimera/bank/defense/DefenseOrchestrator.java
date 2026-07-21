package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.healing.SelfHealingController;
import com.chimera.bank.defense.vault.DeceptionVault;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * End-to-end defense flow controller:
 *
 * <ol>
 *   <li>Run the ordered defense rings ({@link DefensePipeline}).</li>
 *   <li>If the pipeline PASSes, the request is allowed.</li>
 *   <li>If a ring raises a threat (CHALLENGE/QUARANTINE/BLOCK), invoke the
 *       RAG-driven {@link SelfHealingController} to attempt bounded remediation.</li>
 *   <li>If healing succeeds, the session is remediated (allow-with-controls).
 *       If healing fails, re-run the pipeline with {@code self_heal_failed} set
 *       so the deception-vault ring (L6) relocates the session.</li>
 * </ol>
 */
@Component
public class DefenseOrchestrator {

    private final DefensePipeline pipeline;
    private final SelfHealingController healing;
    private final DeceptionVault vault;

    public DefenseOrchestrator(DefensePipeline pipeline, SelfHealingController healing, DeceptionVault vault) {
        this.pipeline = pipeline;
        this.healing = healing;
        this.vault = vault;
    }

    public enum Disposition {ALLOWED, REMEDIATED, VAULTED, BLOCKED}

    public record OrchestrationOutcome(
            String correlationId,
            Disposition disposition,
            LayerVerdict triggeringVerdict,
            SelfHealingController.HealingOutcome healing,
            DefenseResult finalPipeline) {
    }

    public OrchestrationOutcome handle(DefenseContext ctx) {
        DefenseResult first = pipeline.evaluate(ctx);
        LayerVerdict verdict = first.finalVerdict();

        if (first.allowed()) {
            return new OrchestrationOutcome(
                    ctx.correlationId(), Disposition.ALLOWED, verdict, null, first);
        }

        // A hard BLOCK (e.g. RBAC violation, denylisted IP) is a policy decision,
        // not something to "heal" — it stays blocked.
        if (verdict.decision() == LayerVerdict.Decision.BLOCK) {
            return new OrchestrationOutcome(
                    ctx.correlationId(), Disposition.BLOCKED, verdict, null, first);
        }

        // CHALLENGE / QUARANTINE -> attempt RAG-driven self-healing.
        SelfHealingController.HealingOutcome heal = healing.heal(ctx, verdict);
        if (heal.healed()) {
            return new OrchestrationOutcome(
                    ctx.correlationId(), Disposition.REMEDIATED, verdict, heal, first);
        }

        // Healing failed (or self-heal budget exhausted): relocate the session's
        // sensitive working set to the isolated deception vault. This is the L6
        // action performed directly, since an outer terminal ring (e.g. a canary
        // QUARANTINE at L4) would otherwise short-circuit the pipeline before L6.
        Map<String, Object> snapshot = new HashMap<>(ctx.signals());
        snapshot.put("reg_no", ctx.regNo());
        snapshot.put("purpose", ctx.purpose());
        snapshot.put("triggering_layer", verdict.layer());
        vault.quarantine(ctx.correlationId(), "self_heal_failed:" + verdict.layer(), snapshot);
        return new OrchestrationOutcome(
                ctx.correlationId(), Disposition.VAULTED, verdict, heal, first);
    }
}
