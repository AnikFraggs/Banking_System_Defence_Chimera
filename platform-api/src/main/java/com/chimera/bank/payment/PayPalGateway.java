package com.chimera.bank.payment;

import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;

public interface PayPalGateway {
    ProviderResult createOrder(UUID orderId, BigDecimal amount, String currency, String note);

    ProviderResult getOrder(UUID orderId, String paypalOrderId);

    ProviderResult authorizeOrder(UUID orderId, String paypalOrderId, BigDecimal amount, String currency);

    ProviderResult captureAuthorization(UUID orderId, String authorizationId, BigDecimal amount, String currency);

    ProviderResult voidAuthorization(UUID orderId, String authorizationId);

    boolean verifyWebhook(String rawBody, Map<String, String> headers);
}
