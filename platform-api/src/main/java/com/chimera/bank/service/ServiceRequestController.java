package com.chimera.bank.service;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;

/**
 * Client raises invest/buy/deposit/loan requests; accountant approves or
 * rejects. This is the interconnected consult-an-accountant pipeline.
 */
@RestController
@RequestMapping("/api/requests")
public class ServiceRequestController {

    private final AuthService auth;
    private final ServiceRequestService service;

    public ServiceRequestController(AuthService auth, ServiceRequestService service) {
        this.auth = auth;
        this.service = service;
    }

    public record CreateRequest(@NotBlank String type,
                                @NotNull @DecimalMin("0.01") BigDecimal amount,
                                String detail, String paymentMethod, String paymentReference) { }
    public record DecisionRequest(boolean approve, String note) { }

    @PostMapping
    public ServiceRequestEntity create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                       @Valid @RequestBody CreateRequest body) {
        AuthService.Principal client = auth.requireOneOf(authorization, Role.CUSTOMER);
        return service.create(client, body.type(), body.amount(), body.detail(),
                body.paymentMethod(), body.paymentReference());
    }

    @GetMapping("/mine")
    public List<ServiceRequestEntity> mine(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return service.forClient(auth.requireOneOf(authorization, Role.CUSTOMER));
    }

    @GetMapping("/pending")
    public List<ServiceRequestEntity> pending(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return service.pending();
    }

    @GetMapping
    public List<ServiceRequestEntity> all(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return service.all();
    }

    @PostMapping("/{id}/decision")
    public ServiceRequestEntity decide(@RequestHeader(value = "Authorization", required = false) String authorization,
                                       @PathVariable Long id, @RequestBody DecisionRequest body) {
        AuthService.Principal accountant = auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return service.decide(accountant, id, body.approve(), body.note());
    }
}
