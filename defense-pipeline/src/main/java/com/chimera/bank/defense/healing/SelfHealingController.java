package com.chimera.bank.defense.healing;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * RAG-driven self-healing controller.
 *
 * <p>When a layer raises a non-passing verdict, the controller retrieves a
 * remediation playbook from {@link HealingRag} and applies bounded rounds of it.
 * Each round reduces residual threat severity by the playbook's efficacy; the
 * session is considered healed once residual severity falls below a resolve
 * threshold. If the round budget is exhausted first, healing has failed and the
 * controller sets {@code self_heal_failed} on the context so the deception-vault
 * layer (L6) can relocate the session.
 *
 * <p>Remediation is deterministic (efficacy-driven, not random) so simulation
 * results are reproducible.
 */
@Component
public class SelfHealingController {

    private static final Logger log = LoggerFactory.getLogger(SelfHealingController.class);

    private static final int MAX_ROUNDS = 3;          // bounded "heal in time" budget
    private static final double RESOLVE_THRESHOLD = 0.20;
    private static final double MAX_REDUCTION_PER_ROUND = 0.18; // capacity ceiling per round

    private final HealingRag healingRag;

    public SelfHealingController(HealingRag healingRag) {
        this.healingRag = healingRag;
    }

    public record HealingOutcome(
            boolean healed,
            int roundsUsed,
            double initialSeverity,
            double residualSeverity,
            String threatClass,
            String playbookTitle,
            List<String> appliedSteps) {
    }

    public HealingOutcome heal(DefenseContext ctx, LayerVerdict trigger) {
        double severity = trigger.severity();
        HealingPlaybook playbook = healingRag.retrieveForLayer(trigger.layer())
                .orElseGet(healingRag::generic);

        double residual = severity;
        int round = 0;
        List<String> applied = new ArrayList<>();

        while (round < MAX_ROUNDS && residual > RESOLVE_THRESHOLD) {
            String step = playbook.steps().get(Math.min(round, playbook.steps().size() - 1));
            applied.add(step);
            // Each round removes a bounded absolute amount of threat, scaled by the
            // playbook's efficacy and capped by remediation capacity. High-severity
            // threats (e.g. a confirmed data leak) can therefore exhaust the round
            // budget before dropping below the resolve threshold -> heal fails.
            double reduction = Math.min(MAX_REDUCTION_PER_ROUND, playbook.efficacy() * MAX_REDUCTION_PER_ROUND * 1.4);
            residual = Math.max(0.0, residual - reduction);
            round++;
            log.debug("Heal round {} for {} via '{}' -> residual {}",
                    round, trigger.layer(), step, residual);
        }

        boolean healed = residual <= RESOLVE_THRESHOLD;
        ctx.addSignal("heal_threat_class", playbook.threatClass());
        ctx.addSignal("heal_rounds", round);
        ctx.addSignal("heal_residual_severity", round == 0 ? severity : residual);
        ctx.addSignal("healed", healed);
        if (!healed) {
            ctx.addSignal("self_heal_failed", true);
            log.warn("Self-heal FAILED for {} (residual {} after {} rounds); escalating to vault.",
                    trigger.layer(), residual, round);
        }
        return new HealingOutcome(
                healed, round, severity, residual,
                playbook.threatClass(), playbook.title(), applied);
    }
}
