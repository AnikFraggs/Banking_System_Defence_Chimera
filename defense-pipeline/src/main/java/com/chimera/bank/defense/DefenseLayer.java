package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;

/**
 * A single ring in the layered defense. Ordered from outermost (lowest order
 * value) to innermost. Each layer inspects the {@link DefenseContext}, may add
 * signals to it, and returns a {@link LayerVerdict}. Layers must be side-effect
 * free with respect to money movement; they only decide and annotate.
 */
public interface DefenseLayer {

    /** Lower runs first. L1 (IP) is outermost; L6 (deception vault) is innermost. */
    int order();

    String name();

    LayerVerdict inspect(DefenseContext context);
}
