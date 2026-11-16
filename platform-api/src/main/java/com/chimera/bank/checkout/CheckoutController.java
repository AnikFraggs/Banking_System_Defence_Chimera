package com.chimera.bank.checkout;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.idempotency.IdempotencyService;
import com.chimera.bank.common.rbac.Role;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/checkout/orders")
@PreAuthorize("isAuthenticated()")
public class CheckoutController {
    private final CheckoutService checkout;
    private final AuthService auth;
    private final IdempotencyService idempotency;

    public CheckoutController(CheckoutService checkout, AuthService auth, IdempotencyService idempotency) {
        this.checkout = checkout;
        this.auth = auth;
        this.idempotency = idempotency;
    }

    @PostMapping
    public CheckoutDtos.OrderView create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                         @RequestHeader(value = "X-Forwarded-For", required = false) String xForwardedFor,
                                         @RequestHeader(value = "X-Real-IP", required = false) String xRealIp,
                                         @Valid @RequestBody CheckoutDtos.CreateOrderRequest request,
                                         HttpServletRequest servletRequest) {
        AuthService.Principal principal = auth.require(authorization);
        String sourceIp = resolveClientIp(xForwardedFor, xRealIp, servletRequest.getRemoteAddr());
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return checkout.create(principal, request, sourceIp);
        }
        return idempotency.execute(idempotencyKey, "checkout.create", request, CheckoutDtos.OrderView.class,
                () -> checkout.create(principal, request, sourceIp)).value();
    }

    private static String resolveClientIp(String xForwardedFor, String xRealIp, String remoteAddr) {
        if (xForwardedFor != null && !xForwardedFor.isBlank()) {
            // X-Forwarded-For: client, proxy1, proxy2 — take the leftmost (original client).
            String first = xForwardedFor.split(",")[0].trim();
            if (!first.isBlank() && !"unknown".equalsIgnoreCase(first)) {
                return first;
            }
        }
        if (xRealIp != null && !xRealIp.isBlank() && !"unknown".equalsIgnoreCase(xRealIp)) {
            return xRealIp;
        }
        return remoteAddr;
    }

    @PostMapping("/{id}/authorize")
    public CheckoutDtos.OrderView authorize(@RequestHeader(value = "Authorization", required = false) String authorization,
                                            @PathVariable UUID id,
                                            @RequestBody(required = false) CheckoutDtos.AuthorizeRequest request) {
        return checkout.authorize(auth.require(authorization), id,
                request == null ? null : request.telemetry());
    }

    @GetMapping("/{id}")
    public CheckoutDtos.OrderView get(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @PathVariable UUID id) {
        return checkout.get(auth.require(authorization), id);
    }

    @PostMapping("/{id}/step-up/verify")
    public CheckoutDtos.OrderView stepUp(@RequestHeader(value = "Authorization", required = false) String authorization,
                                         @PathVariable UUID id,
                                         @Valid @RequestBody CheckoutDtos.StepUpRequest request) {
        return checkout.verifyStepUp(auth.require(authorization), id, request);
    }
}
