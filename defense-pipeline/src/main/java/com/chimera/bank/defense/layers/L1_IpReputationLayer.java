package com.chimera.bank.defense.layers;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.defense.DefenseLayer;
import org.springframework.stereotype.Component;

import java.util.Set;

/**
 * Layer 1 (outermost): IP reputation and network sanity.
 *
 * <p>Treats network location as a WEAK signal (consistent with zero-trust): it
 * can raise a challenge but, on its own, only blocks explicitly denylisted
 * sources. It never concludes malicious intent from IP alone. In production the
 * static sets below are replaced by a reputation feed / allowlist service.
 */
@Component
public class L1_IpReputationLayer implements DefenseLayer {

    // Illustrative only. Replace with a managed reputation feed.
    private static final Set<String> DENYLIST = Set.of("0.0.0.0", "203.0.113.66");
    private static final Set<String> PRIVATE_PREFIXES = Set.of("10.", "192.168.", "172.16.");

    @Override
    public int order() {
        return 1;
    }

    @Override
    public String name() {
        return "L1_ip_reputation";
    }

    @Override
    public LayerVerdict inspect(DefenseContext ctx) {
        String ip = ctx.sourceIp();
        ctx.addSignal("source_ip_seen", ip != null);

        if (ip == null || ip.isBlank()) {
            return LayerVerdict.challenge(name(), "missing_source_ip", 0.4);
        }
        if (DENYLIST.contains(ip)) {
            return LayerVerdict.block(name(), "denylisted_source_ip", 0.95);
        }
        boolean isPrivate = PRIVATE_PREFIXES.stream().anyMatch(ip::startsWith);
        ctx.addSignal("private_network", isPrivate);
        // A public IP for a privileged/back-office action is worth a soft challenge,
        // but network context alone is never a hard block for a valid identity.
        return LayerVerdict.pass(name());
    }
}
