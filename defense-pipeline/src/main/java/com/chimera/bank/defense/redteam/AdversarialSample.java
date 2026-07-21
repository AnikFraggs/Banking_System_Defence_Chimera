package com.chimera.bank.defense.redteam;

import com.chimera.bank.common.rbac.Role;

/**
 * One labeled adversarial (or benign) sample for exercising the defense pipeline.
 *
 * <p>Every sample carries ground truth — {@code malicious} and a graded
 * {@code expectedSeverity} in [0,1] — plus the attack {@code family} and the
 * {@code targetLayer} it is designed to exercise, so the validation harness can
 * measure per-layer detection accuracy and severity calibration.
 */
public record AdversarialSample(
        String id,
        String family,
        String targetLayer,
        String sourceIp,
        Role role,
        String purpose,
        String payload,
        boolean humanVerified,
        boolean malicious,
        double expectedSeverity) {
}
