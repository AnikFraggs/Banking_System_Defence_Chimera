package com.chimera.bank.simulator;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.checkout.CheckoutDtos;
import com.chimera.bank.checkout.CheckoutService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;

@RestController
@RequestMapping("/api")
public class SimulatorController {
    private final ScenarioCatalog scenarios;
    private final CheckoutService checkout;
    private final AuthService auth;

    public SimulatorController(ScenarioCatalog scenarios, CheckoutService checkout, AuthService auth) {
        this.scenarios = scenarios;
        this.checkout = checkout;
        this.auth = auth;
    }

    @GetMapping("/scenarios")
    public List<CheckoutDtos.ScenarioView> scenarios(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return scenarios.all();
    }

    @PostMapping("/simulator/sessions")
    public CheckoutDtos.OrderView start(@RequestHeader(value = "Authorization", required = false) String authorization,
                                        @Valid @RequestBody CheckoutDtos.ScenarioRequest scenario,
                                        HttpServletRequest servletRequest) {
        AuthService.Principal principal = auth.require(authorization);
        scenarios.require(scenario.scenarioId());
        return checkout.create(principal, new CheckoutDtos.CreateOrderRequest(BigDecimal.ONE, "USD",
                "Simulator placeholder", "CHECKOUT", scenario.scenarioId(), null), servletRequest.getRemoteAddr());
    }
}
