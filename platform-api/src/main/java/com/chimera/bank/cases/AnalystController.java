package com.chimera.bank.cases;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.checkout.CheckoutDtos;
import com.chimera.bank.checkout.CheckoutService;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/analyst")
@PreAuthorize("hasAnyRole('ACCOUNTANT', 'MANAGER')")
public class AnalystController {
    private final CheckoutService checkout;
    private final CaseService cases;
    private final AuthService auth;
    private final AnalystFeedbackPublisher feedback;

    public AnalystController(CheckoutService checkout, CaseService cases, AuthService auth,
                             AnalystFeedbackPublisher feedback) {
        this.checkout = checkout;
        this.cases = cases;
        this.auth = auth;
        this.feedback = feedback;
    }

    @GetMapping("/orders")
    public List<CheckoutDtos.OrderView> orders(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return checkout.list();
    }

    @GetMapping("/cases")
    public List<CaseEntity> cases(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return cases.list();
    }

    @PostMapping("/cases/{id}/verdict")
    public CaseEntity verdict(@RequestHeader(value = "Authorization", required = false) String authorization,
                              @PathVariable UUID id, @Valid @RequestBody VerdictRequest request) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        CaseEntity resolved = cases.verdict(id, request.verdict());
        feedback.publish(resolved);
        return resolved;
    }

    public record VerdictRequest(@NotBlank @Pattern(regexp = "FRAUD|BENIGN|INCONCLUSIVE") String verdict) {}
}
