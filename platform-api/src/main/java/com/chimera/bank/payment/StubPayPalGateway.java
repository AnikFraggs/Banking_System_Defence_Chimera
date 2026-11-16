package com.chimera.bank.payment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;

@Component
@ConditionalOnProperty(name = "chimera.checkout.paypal.mode", havingValue = "stub", matchIfMissing = true)
public class StubPayPalGateway implements PayPalGateway {
    private final PayPalOperationRepository operationRepository;
    private final ObjectMapper objectMapper;

    public StubPayPalGateway(PayPalOperationRepository operationRepository, ObjectMapper objectMapper) {
        this.operationRepository = operationRepository;
        this.objectMapper = objectMapper;
    }

    @Override
    public ProviderResult createOrder(UUID orderId, BigDecimal amount, String currency, String note) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("intent", "AUTHORIZE");
        ObjectNode purchaseUnit = request.putArray("purchase_units").addObject();
        ObjectNode amountNode = purchaseUnit.putObject("amount");
        amountNode.put("currency_code", currency);
        amountNode.put("value", amount.toPlainString());
        if (note != null && !note.isBlank()) {
            purchaseUnit.put("description", note);
        }

        String providerId = "STUB-ORDER-" + orderId;
        ObjectNode response = objectMapper.createObjectNode();
        response.put("id", providerId);
        response.put("status", "CREATED");
        return persistStubOperation("CREATE_ORDER", orderId, request,
                new ProviderResult(providerId, "CREATED", PayPalRequestSupport.canonicalJson(objectMapper, response)));
    }

    @Override
    public ProviderResult getOrder(UUID orderId, String paypalOrderId) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("paypal_order_id", paypalOrderId);
        ObjectNode response = objectMapper.createObjectNode();
        response.put("id", paypalOrderId);
        response.put("status", "APPROVED");
        return persistStubOperation("GET_ORDER", orderId, request,
                new ProviderResult(paypalOrderId, "APPROVED", PayPalRequestSupport.canonicalJson(objectMapper, response)));
    }

    @Override
    public ProviderResult authorizeOrder(UUID orderId, String paypalOrderId, BigDecimal amount, String currency) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("paypal_order_id", paypalOrderId);
        request.putObject("amount").put("currency_code", currency).put("value", amount.toPlainString());

        String authorizationId = "STUB-AUTH-" + paypalOrderId;
        ObjectNode response = objectMapper.createObjectNode();
        response.put("id", paypalOrderId);
        response.put("status", "COMPLETED");
        response.put("authorization_id", authorizationId);
        return persistStubOperation("AUTHORIZE_ORDER", orderId, request,
                new ProviderResult(authorizationId, "COMPLETED", PayPalRequestSupport.canonicalJson(objectMapper, response)));
    }

    @Override
    public ProviderResult captureAuthorization(UUID orderId, String authorizationId, BigDecimal amount, String currency) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("authorization_id", authorizationId);
        request.putObject("amount").put("currency_code", currency).put("value", amount.toPlainString());

        String captureId = "STUB-CAPTURE-" + authorizationId;
        ObjectNode response = objectMapper.createObjectNode();
        response.put("id", captureId);
        response.put("status", "COMPLETED");
        return persistStubOperation("CAPTURE_AUTHORIZATION", orderId, request,
                new ProviderResult(captureId, "COMPLETED", PayPalRequestSupport.canonicalJson(objectMapper, response)));
    }

    @Override
    public ProviderResult voidAuthorization(UUID orderId, String authorizationId) {
        ObjectNode request = objectMapper.createObjectNode();
        request.put("authorization_id", authorizationId);
        ObjectNode response = objectMapper.createObjectNode();
        response.put("id", authorizationId);
        response.put("status", "VOIDED");
        return persistStubOperation("VOID_AUTHORIZATION", orderId, request,
                new ProviderResult(authorizationId, "VOIDED", PayPalRequestSupport.canonicalJson(objectMapper, response)));
    }

    @Override
    public boolean verifyWebhook(String rawBody, Map<String, String> headers) {
        return true;
    }

    private ProviderResult persistStubOperation(String operationType, UUID orderId, ObjectNode request,
                                                 ProviderResult result) {
        String requestBody = PayPalRequestSupport.canonicalJson(objectMapper, request);
        PayPalOperationEntity operation = new PayPalOperationEntity();
        operation.setOrderId(orderId);
        operation.setOperationType(operationType);
        operation.setRequestId(UUID.randomUUID().toString());
        operation.setRequestBody(requestBody);
        operation.setRequestBodyHash(PayPalRequestSupport.sha256(requestBody));
        operation.setStatus("PENDING");
        operationRepository.saveAndFlush(operation);

        operation.setProviderId(result.providerId());
        operation.setStatus(result.status());
        operation.setResponseBody(result.responseBody());
        operationRepository.saveAndFlush(operation);
        return result;
    }
}
