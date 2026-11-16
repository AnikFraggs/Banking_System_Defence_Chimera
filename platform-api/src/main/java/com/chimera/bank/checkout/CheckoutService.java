package com.chimera.bank.checkout;

import com.chimera.bank.audit.AuditLedgerService;
import com.chimera.bank.audit.ReceiptService;
import com.chimera.bank.auth.AuthService;
import com.chimera.bank.cache.OrderCache;
import com.chimera.bank.cases.CaseService;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.fraud.FraudGateTransport;
import com.chimera.bank.fraud.ScoreReason;
import com.chimera.bank.fraud.ScoreRequest;
import com.chimera.bank.fraud.ScoreResponse;
import com.chimera.bank.outbox.OutboxService;
import com.chimera.bank.payment.PayPalGateway;
import com.chimera.bank.payment.ProviderResult;
import com.chimera.bank.saga.SagaOrchestrator;
import com.chimera.bank.simulator.ScenarioCatalog;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class CheckoutService {
    private final CheckoutOrderRepository orders;
    private final RiskDecisionRepository decisions;
    private final CheckoutDefenseService defense;
    private final ScenarioCatalog scenarios;
    private final PayPalGateway payPal;
    private final FraudGateTransport fraudGate;
    private final StepUpService stepUp;
    private final AuditLedgerService audit;
    private final ReceiptService receipts;
    private final CaseService cases;
    private final ObjectMapper objectMapper;
    private final OrderCache cache;
    private final OutboxService outbox;
    private final SagaOrchestrator saga;

    public CheckoutService(CheckoutOrderRepository orders, RiskDecisionRepository decisions,
                           CheckoutDefenseService defense, ScenarioCatalog scenarios, PayPalGateway payPal,
                           FraudGateTransport fraudGate, StepUpService stepUp, AuditLedgerService audit,
                           ReceiptService receipts, CaseService cases, ObjectMapper objectMapper,
                           OrderCache cache, OutboxService outbox, SagaOrchestrator saga) {
        this.orders = orders;
        this.decisions = decisions;
        this.defense = defense;
        this.scenarios = scenarios;
        this.payPal = payPal;
        this.fraudGate = fraudGate;
        this.stepUp = stepUp;
        this.audit = audit;
        this.receipts = receipts;
        this.cases = cases;
        this.objectMapper = objectMapper;
        this.cache = cache;
        this.outbox = outbox;
        this.saga = saga;
    }

    @Transactional
    public CheckoutDtos.OrderView create(AuthService.Principal principal,
                                         CheckoutDtos.CreateOrderRequest original, String sourceIp) {
        CheckoutDtos.CreateOrderRequest request = scenarios.apply(original);
        if (!"USD".equals(request.currency())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Checkout Shield sandbox orders use USD");
        }
        CheckoutOrderEntity order = new CheckoutOrderEntity();
        order.setId(UUID.randomUUID());
        order.setUsername(principal.registrationNumber());
        order.setBuyerRole(principal.role().name());
        order.setAmount(request.amount());
        order.setCurrency(request.currency());
        order.setNote(request.note());
        String purpose = request.purpose() == null ? "CHECKOUT" : request.purpose();
        order.setPurpose(purpose);
        order.setScenarioId(request.scenarioId());
        order.setSimulated(request.scenarioId() != null && !request.scenarioId().isBlank());
        order.setState(OrderState.CREATED);
        orders.save(order);

        CheckoutDefenseService.Outcome checked = defense.inspect(order.getId().toString(), sourceIp,
                principal.registrationNumber(), principal.role(), purpose.toLowerCase(), request.note());
        if (!checked.allowed()) {
            order.setState(OrderState.BLOCKED);
            order.setScore(checked.severity());
            order.setAction(checked.severity() >= 0.7 ? "VOID" : "CHALLENGE");
            order.setReasonsJson(writeReasons(List.of(new ScoreReason("DEFENSE_BLOCK", checked.message(),
                    "CHIMERA", checked.severity()))));
            orders.save(order);
            audit.append(order.getId(), "DEFENSE_BLOCKED", Map.of("reason", checked.message()));
            outbox.record("CheckoutOrder", order.getId(), "ORDER_BLOCKED", Map.of("reason", checked.message()));
            cache.evict(order.getId());
            return view(order, null);
        }

        try {
            ProviderResult created = payPal.createOrder(order.getId(), order.getAmount(), order.getCurrency(), order.getNote());
            order.setPaypalOrderId(created.providerId());
            orders.save(order);
            audit.append(order.getId(), "PAYPAL_ORDER_CREATED",
                    Map.of("paypalOrderId", created.providerId(), "status", created.status()));
            outbox.record("CheckoutOrder", order.getId(), "ORDER_CREATED",
                    Map.of("paypalOrderId", created.providerId(), "amount", order.getAmount().toPlainString()));
            cache.evict(order.getId());
            return view(order, null);
        } catch (RuntimeException e) {
            order.setState(OrderState.EXPIRED);
            orders.save(order);
            audit.append(order.getId(), "PAYPAL_ORDER_CREATE_FAILED", Map.of("error", e.getClass().getSimpleName()));
            throw e;
        }
    }

    @Transactional
    public CheckoutDtos.OrderView authorize(AuthService.Principal principal, UUID id,
                                            CheckoutDtos.Telemetry telemetry) {
        CheckoutOrderEntity order = ownedForUpdate(principal, id);
        if (order.getState().terminal()) return view(order, null);
        if (order.getState() != OrderState.CREATED && order.getState() != OrderState.APPROVED) {
            throw conflict("Order cannot be approved from state " + order.getState());
        }
        if (order.getState() == OrderState.CREATED) {
            ProviderResult approved = payPal.getOrder(order.getId(), order.getPaypalOrderId());
            if (!"APPROVED".equalsIgnoreCase(approved.status())) {
                throw conflict("PayPal buyer approval is not complete");
            }
            transition(order, OrderState.APPROVED, "PAYPAL_BUYER_APPROVED");
        }
        ProviderResult authorized = payPal.authorizeOrder(order.getId(), order.getPaypalOrderId(),
                order.getAmount(), order.getCurrency());
        order.setPaypalAuthorizationId(authorized.providerId());
        orders.save(order);
        transition(order, OrderState.AUTHORIZED, "PAYPAL_AUTHORIZED");
        audit.append(order.getId(), "PAYPAL_AUTHORIZATION_CONFIRMED", Map.of(
                "paypalOrderId", order.getPaypalOrderId(),
                "paypalAuthorizationId", authorized.providerId()));
        return scoreAndSettle(order, "INITIAL", telemetry, false);
    }

    @Transactional
    public CheckoutDtos.OrderView verifyStepUp(AuthService.Principal principal, UUID id,
                                               CheckoutDtos.StepUpRequest request) {
        CheckoutOrderEntity order = ownedForUpdate(principal, id);
        if (order.getState() != OrderState.STEP_UP) throw conflict("Order is not awaiting step-up");
        StepUpService.Verification verification = stepUp.verify(id, request.code());
        if (verification == StepUpService.Verification.INVALID) {
            order.setAction("CHALLENGE");
            order.setReasonsJson(writeReasons(List.of(new ScoreReason("STEP_UP_INVALID",
                    "Verification code is invalid; remaining attempts are limited", "STEP_UP", 0.5))));
            orders.save(order);
            audit.append(id, "STEP_UP_INVALID", Map.of());
            return view(order, null);
        }
        if (verification != StepUpService.Verification.SUCCESS) {
            audit.append(id, "STEP_UP_FAILED", Map.of("result", verification.name()));
            return voidOrder(order);
        }
        transition(order, OrderState.SCORED, "STEP_UP_VERIFIED");
        return scoreAndSettle(order, "RESCORE", request.telemetry(), true);
    }

    @Transactional(readOnly = true)
    public CheckoutDtos.OrderView get(AuthService.Principal principal, UUID id) {
        OrderCache.CachedOrder cached = cache.get(id, () -> {
            CheckoutOrderEntity order = orders.findById(id).orElseThrow(() -> notFound("Checkout order not found"));
            requireAccess(principal, order);
            return new OrderCache.CachedOrder(order.getUsername(), view(order, null));
        });
        // Re-authorize on cache hits too: the cached owner must match the requesting customer.
        if (principal.role() == Role.CUSTOMER && !cached.username().equals(principal.registrationNumber())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "This checkout belongs to another customer");
        }
        return cached.view();
    }

    @Transactional(readOnly = true)
    public List<CheckoutDtos.OrderView> list() {
        return orders.findTop100ByOrderByCreatedAtDesc().stream().map(order -> view(order, null)).toList();
    }

    private CheckoutDtos.OrderView scoreAndSettle(CheckoutOrderEntity order, String mode,
                                                  CheckoutDtos.Telemetry telemetry, boolean stepUpVerified) {
        if (order.getState() == OrderState.AUTHORIZED) transition(order, OrderState.SCORED, "SCORING_STARTED");
        ScoreRequest request = scenarios.scoreRequest(order, mode, telemetry, stepUpVerified);
        ScoreResponse response = fraudGate.score(request);
        persistDecision(order, mode, response);
        if ("CAPTURE".equals(response.action())) {
            ScoreRequest quickRequest = scenarios.scoreRequest(order, "QUICK_RECHECK", telemetry, stepUpVerified);
            ScoreResponse quick = fraudGate.score(quickRequest);
            persistDecision(order, "QUICK_RECHECK", quick);
            if ("CAPTURE".equals(quick.action())) return capture(order);
            return routeNonCapture(order, quick);
        }
        return routeNonCapture(order, response);
    }

    private CheckoutDtos.OrderView routeNonCapture(CheckoutOrderEntity order, ScoreResponse response) {
        if ("VOID".equals(response.action())) return voidOrder(order);
        transition(order, OrderState.STEP_UP, "STEP_UP_REQUIRED");
        String code = stepUp.issue(order.getId());
        if ("ai-receipt".equals(order.getScenarioId())) cases.open(order.getId());
        orders.save(order);
        return view(order, code);
    }

    private CheckoutDtos.OrderView capture(CheckoutOrderEntity order) {
        saga.execute(order.getId(), "SETTLEMENT", List.of(
                new SagaOrchestrator.Step("CAPTURE",
                        () -> {
                            ProviderResult captured = payPal.captureAuthorization(order.getId(),
                                    order.getPaypalAuthorizationId(), order.getAmount(), order.getCurrency());
                            order.setCaptureId(captured.providerId());
                            orders.save(order);
                            transition(order, OrderState.CAPTURED, "PAYPAL_CAPTURED");
                            audit.append(order.getId(), "PAYPAL_CAPTURE_CONFIRMED", Map.of(
                                    "paypalAuthorizationId", order.getPaypalAuthorizationId(),
                                    "captureId", captured.providerId()));
                        },
                        // Compensating transaction: undo the external capture. The local DB state
                        // reverts via the surrounding transaction rollback.
                        () -> payPal.voidAuthorization(order.getId(), order.getPaypalAuthorizationId())),
                new SagaOrchestrator.Step("RECEIPT",
                        () -> {
                            order.setReceiptAvailable(true);
                            orders.saveAndFlush(order);
                            receipts.issue(order);
                        },
                        () -> { }),
                new SagaOrchestrator.Step("OUTBOX",
                        () -> outbox.record("CheckoutOrder", order.getId(), "ORDER_CAPTURED", Map.of(
                                "captureId", order.getCaptureId() == null ? "" : order.getCaptureId(),
                                "amount", order.getAmount().toPlainString())),
                        () -> { })));
        cache.evict(order.getId());
        return view(order, null);
    }

    private CheckoutDtos.OrderView voidOrder(CheckoutOrderEntity order) {
        ProviderResult voided = payPal.voidAuthorization(order.getId(), order.getPaypalAuthorizationId());
        order.setAction("VOID");
        orders.save(order);
        transition(order, OrderState.VOIDED, "PAYPAL_VOIDED");
        audit.append(order.getId(), "PAYPAL_VOID_CONFIRMED", Map.of(
                "paypalAuthorizationId", order.getPaypalAuthorizationId(),
                "providerStatus", voided.status()));
        outbox.record("CheckoutOrder", order.getId(), "ORDER_VOIDED", Map.of(
                "paypalAuthorizationId", order.getPaypalAuthorizationId() == null ? "" : order.getPaypalAuthorizationId()));
        cases.open(order.getId());
        return view(order, null);
    }

    private void persistDecision(CheckoutOrderEntity order, String mode, ScoreResponse response) {
        try {
            RiskDecisionEntity decision = new RiskDecisionEntity();
            decision.setOrderId(order.getId());
            decision.setMode(mode);
            decision.setScore(response.score());
            decision.setAction(response.action());
            decision.setReasonsJson(objectMapper.writeValueAsString(response.reasons()));
            decision.setComponentScoresJson(objectMapper.writeValueAsString(response.componentScores()));
            decision.setModelVersion(response.modelVersion());
            decision.setFeatureHash(response.featureHash());
            decision.setFallback(response.fallback());
            decision.setLatencyMs(response.latencyMs());
            decisions.save(decision);

            order.setScore(response.score());
            order.setAction(response.action());
            order.setReasonsJson(decision.getReasonsJson());
            orders.save(order);
            cache.evict(order.getId());
            audit.append(order.getId(), "RISK_DECISION", Map.of(
                    "mode", mode,
                    "decisionId", response.decisionId() == null ? "" : response.decisionId(),
                    "paypalAuthorizationId", order.getPaypalAuthorizationId(),
                    "score", response.score(),
                    "action", response.action(),
                    "reasons", response.reasons(),
                    "modelVersion", response.modelVersion() == null ? "" : response.modelVersion(),
                    "featureHash", response.featureHash() == null ? "" : response.featureHash(),
                    "fallback", response.fallback()));
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("Could not persist risk decision", e);
        }
    }

    private void transition(CheckoutOrderEntity order, OrderState next, String auditEvent) {
        OrderState current = order.getState();
        if (!current.canTransitionTo(next)) {
            throw conflict("Illegal checkout transition " + current + " -> " + next);
        }
        order.setState(next);
        orders.save(order);
        cache.evict(order.getId());
        audit.append(order.getId(), auditEvent, Map.of("from", current.name(), "to", next.name()));
    }

    private CheckoutOrderEntity ownedForUpdate(AuthService.Principal principal, UUID id) {
        CheckoutOrderEntity order = orders.findForUpdate(id).orElseThrow(() -> notFound("Checkout order not found"));
        requireAccess(principal, order);
        return order;
    }

    private void requireAccess(AuthService.Principal principal, CheckoutOrderEntity order) {
        if (principal.role() == Role.CUSTOMER && !order.getUsername().equals(principal.registrationNumber())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "This checkout belongs to another customer");
        }
    }

    public CheckoutDtos.OrderView view(CheckoutOrderEntity order, String demoOtp) {
        return new CheckoutDtos.OrderView(order.getId(), order.getPaypalOrderId(), order.getPaypalAuthorizationId(),
                order.getCaptureId(), order.getState(), order.getAmount(), order.getCurrency(), order.getScore(),
                order.getAction(), readReasons(order.getReasonsJson()), order.getScenarioId(), order.isSimulated(),
                order.getState() == OrderState.STEP_UP, demoOtp, order.isReceiptAvailable(),
                order.getCreatedAt(), order.getUpdatedAt());
    }

    private String writeReasons(List<ScoreReason> reasons) {
        try {
            return objectMapper.writeValueAsString(reasons);
        } catch (Exception e) {
            throw new IllegalStateException("Could not serialize decision reasons", e);
        }
    }

    private List<ScoreReason> readReasons(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return objectMapper.readValue(json, new TypeReference<>() {});
        } catch (Exception e) {
            return List.of(new ScoreReason("DECISION_UNAVAILABLE", "Decision reasons could not be read"));
        }
    }

    private ResponseStatusException conflict(String message) {
        return new ResponseStatusException(HttpStatus.CONFLICT, message);
    }

    private ResponseStatusException notFound(String message) {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, message);
    }
}
