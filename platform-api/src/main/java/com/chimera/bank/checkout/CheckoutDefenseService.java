package com.chimera.bank.checkout;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.DefensePipeline;
import com.chimera.bank.defense.DefenseResult;
import com.chimera.bank.defense.detect.CanaryTokenRegistry;
import com.chimera.bank.defense.detect.SemanticInjectionGuard;
import com.chimera.bank.defense.layers.L1_IpReputationLayer;
import com.chimera.bank.defense.layers.L2_RoleStatusLayer;
import com.chimera.bank.defense.layers.L3_PurposeLayer;
import com.chimera.bank.defense.layers.L4_InjectionLeakLayer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;

@Service
public class CheckoutDefenseService {
    public record Outcome(boolean allowed, String code, String message, double severity) {}

    private final DefensePipeline pipeline;
    private final SemanticInjectionGuard semanticGuard;

    public CheckoutDefenseService(CanaryTokenRegistry canaries) {
        this(canaries, SemanticInjectionGuard.disabled());
    }

    @Autowired
    public CheckoutDefenseService(CanaryTokenRegistry canaries, SemanticInjectionGuard semanticGuard) {
        this.semanticGuard = semanticGuard;
        this.pipeline = new DefensePipeline(List.of(
                new L1_IpReputationLayer(),
                new L2_RoleStatusLayer(),
                new L3_PurposeLayer(),
                new L4_InjectionLeakLayer(canaries,
                        com.chimera.bank.defense.ai.SeverityAdvisor.LOCAL_ONLY, semanticGuard)
        ));
    }

    public SemanticInjectionGuard.Status semanticGuardStatus() {
        return semanticGuard.status();
    }

    public Outcome inspect(String correlationId, String sourceIp, String username, Role role,
                           String purpose, String note) {
        DefenseContext context = new DefenseContext(correlationId, Instant.now(), sourceIp,
                username, role, purpose, note);
        DefenseResult result = pipeline.evaluate(context);
        LayerVerdict verdict = result.finalVerdict();
        return new Outcome(result.allowed(), verdict.reason(),
                verdict.layer() + ": " + verdict.reason(), verdict.severity());
    }
}
