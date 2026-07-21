package com.chimera.bank.common.defense;

/**
 * The outcome a single defense layer returns. Layers can PASS (hand to the next
 * layer), CHALLENGE (require step-up / human proof), QUARANTINE (route to the
 * deception vault), or BLOCK. Verdicts only ever escalate as they move inward;
 * a later layer never downgrades an earlier BLOCK/QUARANTINE.
 */
public record LayerVerdict(Decision decision, String layer, String reason, double severity) {

    public enum Decision {
        PASS(0),
        CHALLENGE(1),
        QUARANTINE(2),
        BLOCK(3);

        private final int rank;

        Decision(int rank) {
            this.rank = rank;
        }

        public int rank() {
            return rank;
        }
    }

    public static LayerVerdict pass(String layer) {
        return new LayerVerdict(Decision.PASS, layer, "ok", 0.0);
    }

    public static LayerVerdict challenge(String layer, String reason, double severity) {
        return new LayerVerdict(Decision.CHALLENGE, layer, reason, severity);
    }

    public static LayerVerdict quarantine(String layer, String reason, double severity) {
        return new LayerVerdict(Decision.QUARANTINE, layer, reason, severity);
    }

    public static LayerVerdict block(String layer, String reason, double severity) {
        return new LayerVerdict(Decision.BLOCK, layer, reason, severity);
    }

    public boolean isTerminal() {
        return decision == Decision.BLOCK || decision == Decision.QUARANTINE;
    }
}
