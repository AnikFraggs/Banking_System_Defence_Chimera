package com.chimera.bank.checkout;

import com.chimera.bank.audit.AuditLedgerService;
import com.chimera.bank.audit.ReceiptService;
import com.chimera.bank.auth.AuthService;
import com.chimera.bank.cache.OrderCache;
import com.chimera.bank.cases.CaseService;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.fraud.FraudGateClient;
import com.chimera.bank.fraud.ScoreReason;
import com.chimera.bank.fraud.ScoreRequest;
import com.chimera.bank.fraud.ScoreResponse;
import com.chimera.bank.outbox.OutboxService;
import com.chimera.bank.payment.PayPalGateway;
import com.chimera.bank.payment.ProviderResult;
import com.chimera.bank.saga.SagaInstanceRepository;
import com.chimera.bank.saga.SagaLog;
import com.chimera.bank.saga.SagaOrchestrator;
import com.chimera.bank.simulator.ScenarioCatalog;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CheckoutServiceTest {
    private CheckoutOrderRepository orders;
    private CheckoutDefenseService defense;
    private PayPalGateway payPal;
    private FraudGateClient fraudGate;
    private CheckoutService service;
    private AuthService.Principal principal;

    @BeforeEach
    void setUp() {
        orders = mock(CheckoutOrderRepository.class);
        defense = mock(CheckoutDefenseService.class);
        payPal = mock(PayPalGateway.class);
        fraudGate = mock(FraudGateClient.class);
        when(orders.save(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(orders.saveAndFlush(any())).thenAnswer(invocation -> invocation.getArgument(0));
        ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        service = new CheckoutService(orders, mock(RiskDecisionRepository.class), defense, new ScenarioCatalog(),
                payPal, fraudGate, mock(StepUpService.class), mock(AuditLedgerService.class),
                mock(ReceiptService.class), mock(CaseService.class), mapper,
                mock(OrderCache.class), mock(OutboxService.class),
                new SagaOrchestrator(new SagaLog(mock(SagaInstanceRepository.class)), new SimpleMeterRegistry()));
        principal = new AuthService.Principal("client", "Client", Role.CUSTOMER, Instant.now().plusSeconds(3600));
    }

    @Test
    void defenseBlockMakesNoPayPalCall() {
        when(defense.inspect(any(), any(), any(), any(), any(), any()))
                .thenReturn(new CheckoutDefenseService.Outcome(false, "injection", "L4 injection", 0.95));
        CheckoutDtos.CreateOrderRequest request = request("benign");
        CheckoutDtos.OrderView result = service.create(principal, request, "127.0.0.1");

        assertEquals(OrderState.BLOCKED, result.state());
        verify(payPal, never()).createOrder(any(), any(), any(), any());
    }

    @Test
    void lowRiskStillRequiresQuickRecheckBeforeCapture() {
        when(defense.inspect(any(), any(), any(), any(), any(), any()))
                .thenReturn(new CheckoutDefenseService.Outcome(true, "ok", "ok", 0));
        when(payPal.createOrder(any(), any(), any(), any())).thenReturn(new ProviderResult("PAYPAL-1", "CREATED", "{}"));
        when(payPal.getOrder(any(), any())).thenReturn(new ProviderResult("PAYPAL-1", "APPROVED", "{}"));
        when(payPal.authorizeOrder(any(), any(), any(), any())).thenReturn(new ProviderResult("AUTH-1", "COMPLETED", "{}"));
        when(payPal.captureAuthorization(any(), any(), any(), any())).thenReturn(new ProviderResult("CAP-1", "COMPLETED", "{}"));
        ScoreResponse capture = new ScoreResponse("decision", 0.1, "CAPTURE",
                List.of(new ScoreReason("LOW_RISK", "Low risk", "CARD", 0.1)), Map.of(), "test", "hash", false, 5);
        when(fraudGate.score(any())).thenReturn(capture);

        CheckoutDtos.OrderView created = service.create(principal, request(null), "127.0.0.1");
        when(orders.findForUpdate(created.id())).thenReturn(Optional.of(orderWithId(created.id())));
        CheckoutDtos.OrderView result = service.authorize(principal, created.id(), null);

        assertEquals(OrderState.CAPTURED, result.state());
        assertEquals("CAP-1", result.captureId());
        verify(fraudGate, org.mockito.Mockito.times(2)).score(any(ScoreRequest.class));
        verify(payPal).captureAuthorization(any(), any(), any(), any());
    }

    private CheckoutOrderEntity orderWithId(UUID id) {
        CheckoutOrderEntity order = new CheckoutOrderEntity();
        order.setId(id);
        order.setUsername("client");
        order.setBuyerRole("CUSTOMER");
        order.setAmount(new BigDecimal("25.00"));
        order.setCurrency("USD");
        order.setNote("A ordinary sandbox order");
        order.setPurpose("CHECKOUT");
        order.setState(OrderState.CREATED);
        order.setPaypalOrderId("PAYPAL-1");
        return order;
    }

    private CheckoutDtos.CreateOrderRequest request(String scenarioId) {
        return new CheckoutDtos.CreateOrderRequest(new BigDecimal("25.00"), "USD", "A ordinary sandbox order",
                "CHECKOUT", scenarioId, null);
    }
}
