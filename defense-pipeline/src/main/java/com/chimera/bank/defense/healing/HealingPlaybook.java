package com.chimera.bank.defense.healing;

import java.util.List;

/**
 * A remediation playbook retrieved by the healing RAG for a given threat class.
 * Each playbook lists ordered, bounded, reversible remediation steps and an
 * estimated efficacy in [0,1] — the probability a single application resolves
 * the threat. Efficacy drives how many rounds the self-healing controller needs.
 */
public record HealingPlaybook(
        String threatClass,
        String title,
        List<String> steps,
        double efficacy) {
}
