package com.chimera.bank.payment;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

@Component
@ConditionalOnProperty(name = "chimera.checkout.paypal.mode", havingValue = "http")
public class HttpPayPalGateway implements PayPalGateway {
    private static final String CREATE_ORDER = "CREATE_ORDER";
    private static final String GET_ORDER = "GET_ORDER";
    private static final String AUTHORIZE_ORDER = "AUTHORIZE_ORDER";
    private static final String CAPTURE_AUTHORIZATION = "CAPTURE_AUTHORIZATION";
    private static final String VOID_AUTHORIZATION = "VOID_AUTHORIZATION";

    private final PayPalOperationRepository operationRepository;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final String baseUrl;
    private final String clientId;
    private final String clientSecret;
    private final String webhookId;
    private final Duration readTimeout;
    private final Object tokenMonitor = new Object();
    private volatile OAuthToken cachedToken;

    public HttpPayPalGateway(
            PayPalOperationRepository operationRepository,
            ObjectMapper objectMapper,
            @Value("${chimera.checkout.paypal.base-url:https://api-m.sandbox.paypal.com}") String baseUrl,
            @Value("${chimera.checkout.paypal.client-id:}") String clientId,
            @Value("${chimera.checkout.paypal.client-secret:}") String clientSecret,
            @Value("${chimera.checkout.paypal.webhook-id:}") String webhookId,
            @Value("${chimera.checkout.paypal.connect-timeout:5s}") Duration connectTimeout,
            @Value("${chimera.checkout.paypal.read-timeout:10s}") Duration readTimeout) {
        this.operationRepository = operationRepository;
        this.objectMapper = objectMapper;
        this.baseUrl = validateBaseUrl(baseUrl);
        this.clientId = requireConfiguration(clientId, "PayPal client ID");
        this.clientSecret = requireConfiguration(clientSecret, "PayPal client secret");
        this.webhookId = webhookId == null ? "" : webhookId;
        this.readTimeout = readTimeout;
        this.httpClient = HttpClient.newBuilder().connectTimeout(connectTimeout).build();
    }

    @Override
    public ProviderResult createOrder(UUID orderId, BigDecimal amount, String currency, String note) {
        Objects.requireNonNull(orderId, "orderId");
        ObjectNode request = objectMapper.createObjectNode();
        request.put("intent", "AUTHORIZE");
        ObjectNode purchaseUnit = request.putArray("purchase_units").addObject();
        putAmount(purchaseUnit.putObject("amount"), amount, currency);
        if (note != null && !note.isBlank()) {
            purchaseUnit.put("description", note);
        }

        return execute(CREATE_ORDER, orderId, request,
                requestId -> sendApiRequest("POST", "/v2/checkout/orders", requestId, request),
                responseBody -> {
                    JsonNode root = readJson(responseBody);
                    String providerId = requiredText(root, "id");
                    return new ProviderResult(providerId, status(root, "CREATED"), responseBody);
                });
    }

    @Override
    public ProviderResult getOrder(UUID orderId, String paypalOrderId) {
        Objects.requireNonNull(orderId, "orderId");
        ObjectNode logicalRequest = objectMapper.createObjectNode();
        logicalRequest.put("paypal_order_id", requireProviderId(paypalOrderId));
        String path = "/v2/checkout/orders/" + pathSegment(paypalOrderId);

        return execute(GET_ORDER, orderId, logicalRequest,
                requestId -> sendApiRequest("GET", path, requestId, null),
                responseBody -> {
                    JsonNode root = readJson(responseBody);
                    String providerId = root.path("id").asText("").isBlank() ? paypalOrderId : root.path("id").asText();
                    return new ProviderResult(providerId, status(root, "UNKNOWN"), responseBody);
                });
    }

    @Override
    public ProviderResult authorizeOrder(UUID orderId, String paypalOrderId, BigDecimal amount, String currency) {
        Objects.requireNonNull(orderId, "orderId");
        requireProviderId(paypalOrderId);
        ObjectNode request = objectMapper.createObjectNode();
        putAmount(request.putObject("amount"), amount, currency);
        ObjectNode logicalRequest = request.deepCopy();
        logicalRequest.put("paypal_order_id", paypalOrderId);
        String path = "/v2/checkout/orders/" + pathSegment(paypalOrderId) + "/authorize";

        return execute(AUTHORIZE_ORDER, orderId, logicalRequest,
                requestId -> sendApiRequest("POST", path, requestId, request),
                responseBody -> {
                    JsonNode root = readJson(responseBody);
                    JsonNode authorization = root.path("purchase_units").path(0)
                            .path("payments").path("authorizations").path(0);
                    String authorizationId = requiredText(authorization, "id");
                    return new ProviderResult(authorizationId, status(root, "COMPLETED"), responseBody);
                });
    }

    @Override
    public ProviderResult captureAuthorization(UUID orderId, String authorizationId, BigDecimal amount, String currency) {
        Objects.requireNonNull(orderId, "orderId");
        requireProviderId(authorizationId);
        ObjectNode request = objectMapper.createObjectNode();
        putAmount(request.putObject("amount"), amount, currency);
        ObjectNode logicalRequest = request.deepCopy();
        logicalRequest.put("authorization_id", authorizationId);
        String path = "/v2/payments/authorizations/" + pathSegment(authorizationId) + "/captures";

        return execute(CAPTURE_AUTHORIZATION, orderId, logicalRequest,
                requestId -> sendApiRequest("POST", path, requestId, request),
                responseBody -> {
                    JsonNode root = readJson(responseBody);
                    String captureId = requiredText(root, "id");
                    return new ProviderResult(captureId, status(root, "COMPLETED"), responseBody);
                });
    }

    @Override
    public ProviderResult voidAuthorization(UUID orderId, String authorizationId) {
        Objects.requireNonNull(orderId, "orderId");
        requireProviderId(authorizationId);
        ObjectNode request = objectMapper.createObjectNode();
        ObjectNode logicalRequest = objectMapper.createObjectNode();
        logicalRequest.put("authorization_id", authorizationId);
        String path = "/v2/payments/authorizations/" + pathSegment(authorizationId) + "/void";

        return execute(VOID_AUTHORIZATION, orderId, logicalRequest,
                requestId -> sendApiRequest("POST", path, requestId, request),
                responseBody -> new ProviderResult(authorizationId, "VOIDED", responseBody));
    }

    @Override
    public boolean verifyWebhook(String rawBody, Map<String, String> headers) {
        if (webhookId.isBlank()) {
            throw new IllegalStateException("PayPal webhook ID is not configured.");
        }

        String transmissionId = header(headers, "PAYPAL-TRANSMISSION-ID");
        String transmissionTime = header(headers, "PAYPAL-TRANSMISSION-TIME");
        String transmissionSignature = header(headers, "PAYPAL-TRANSMISSION-SIG");
        String certificateUrl = header(headers, "PAYPAL-CERT-URL");
        String authAlgorithm = header(headers, "PAYPAL-AUTH-ALGO");
        if (isBlank(transmissionId) || isBlank(transmissionTime) || isBlank(transmissionSignature)
                || isBlank(certificateUrl) || isBlank(authAlgorithm)) {
            return false;
        }

        JsonNode event;
        try {
            event = objectMapper.readTree(rawBody);
        } catch (IOException | IllegalArgumentException exception) {
            return false;
        }
        if (event == null || !event.isObject()) {
            return false;
        }

        ObjectNode verification = objectMapper.createObjectNode();
        verification.put("auth_algo", authAlgorithm);
        verification.put("cert_url", certificateUrl);
        verification.put("transmission_id", transmissionId);
        verification.put("transmission_sig", transmissionSignature);
        verification.put("transmission_time", transmissionTime);
        verification.put("webhook_id", webhookId);
        verification.set("webhook_event", event);

        try {
            HttpRequest request = authorizedRequest("/v1/notifications/verify-webhook-signature")
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            PayPalRequestSupport.canonicalJson(objectMapper, verification), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (!isSuccessful(response.statusCode())) {
                throw badGateway("PayPal webhook verification failed (HTTP " + response.statusCode() + ").", null);
            }
            JsonNode result = readJson(response.body());
            return "SUCCESS".equals(result.path("verification_status").asText(""));
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw badGateway("PayPal webhook verification was interrupted.", exception);
        } catch (IOException exception) {
            throw badGateway("PayPal webhook verification is unavailable.", exception);
        }
    }

    private ProviderResult execute(String operationType, UUID orderId, Object logicalRequest,
                                   RequestSender sender, ResponseParser parser) {
        String canonicalRequest = PayPalRequestSupport.canonicalJson(objectMapper, logicalRequest);
        String requestHash = PayPalRequestSupport.sha256(canonicalRequest);
        Optional<PayPalOperationEntity> reusable = operationRepository
                .findFirstByOperationTypeAndOrderIdAndRequestBodyHashAndStatusInOrderByCreatedAtDesc(
                        operationType, orderId, requestHash, List.of("UNKNOWN", "PENDING"));

        PayPalOperationEntity operation;
        if (reusable.isPresent()) {
            operation = reusable.get();
            if (CAPTURE_AUTHORIZATION.equals(operationType) || VOID_AUTHORIZATION.equals(operationType)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "The previous PayPal " + operationType + " outcome is unresolved; reconcile it before retrying.");
            }
            operation.setStatus("PENDING");
            operation.setResponseBody(null);
        } else {
            operation = new PayPalOperationEntity();
            operation.setOrderId(orderId);
            operation.setOperationType(operationType);
            operation.setRequestId(UUID.randomUUID().toString());
            operation.setRequestBody(canonicalRequest);
            operation.setRequestBodyHash(requestHash);
            operation.setStatus("PENDING");
            Instant now = Instant.now();
            operation.setCreatedAt(now);
            operation.setUpdatedAt(now);
        }
        // Flush before any provider request so an idempotency key survives a crash.
        operationRepository.saveAndFlush(operation);

        HttpResponse<String> response;
        try {
            response = sender.send(operation.getRequestId());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            markFailure(operation, "UNKNOWN", null);
            throw badGateway("PayPal request was interrupted; its outcome is unknown.", exception);
        } catch (IOException exception) {
            markFailure(operation, "UNKNOWN", null);
            throw badGateway("PayPal request failed; its outcome is unknown.", exception);
        } catch (ResponseStatusException exception) {
            markFailure(operation, "FAILED", null);
            throw exception;
        } catch (RuntimeException exception) {
            markFailure(operation, "FAILED", null);
            throw badGateway("PayPal request could not be sent.", exception);
        }

        if (!isSuccessful(response.statusCode())) {
            String outcome = response.statusCode() >= 500 ? "UNKNOWN" : "FAILED";
            markFailure(operation, outcome, response.body());
            throw badGateway("PayPal request failed (HTTP " + response.statusCode() + ").", null);
        }

        ProviderResult result;
        try {
            result = parser.parse(response.body());
        } catch (IOException | RuntimeException exception) {
            boolean uncertain = CAPTURE_AUTHORIZATION.equals(operationType) || VOID_AUTHORIZATION.equals(operationType);
            markFailure(operation, uncertain ? "UNKNOWN" : "FAILED", response.body());
            throw badGateway("PayPal returned an invalid response.", exception);
        }

        operation.setProviderId(result.providerId());
        operation.setStatus(result.status());
        operation.setResponseBody(result.responseBody());
        operationRepository.saveAndFlush(operation);
        return result;
    }

    private HttpResponse<String> sendApiRequest(String method, String path, String requestId, JsonNode body)
            throws IOException, InterruptedException {
        HttpRequest.Builder builder = authorizedRequest(path)
                .header("PayPal-Request-Id", requestId);
        if ("GET".equals(method)) {
            builder.GET();
        } else {
            builder.header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            PayPalRequestSupport.canonicalJson(objectMapper, body), StandardCharsets.UTF_8));
        }
        return httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private HttpRequest.Builder authorizedRequest(String path) throws IOException, InterruptedException {
        return HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(readTimeout)
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + accessToken());
    }

    private String accessToken() throws IOException, InterruptedException {
        OAuthToken current = cachedToken;
        if (isUsable(current)) {
            return current.value();
        }

        synchronized (tokenMonitor) {
            current = cachedToken;
            if (isUsable(current)) {
                return current.value();
            }

            String basic = Base64.getEncoder().encodeToString(
                    (clientId + ":" + clientSecret).getBytes(StandardCharsets.UTF_8));
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + "/v1/oauth2/token"))
                    .timeout(readTimeout)
                    .header("Accept", "application/json")
                    .header("Authorization", "Basic " + basic)
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString("grant_type=client_credentials", StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (!isSuccessful(response.statusCode())) {
                throw badGateway("PayPal authentication failed (HTTP " + response.statusCode() + ").", null);
            }
            JsonNode tokenResponse = readJson(response.body());
            String token = requiredText(tokenResponse, "access_token");
            long expiresIn = Math.max(1L, tokenResponse.path("expires_in").asLong(300L));
            cachedToken = new OAuthToken(token, Instant.now().plusSeconds(expiresIn));
            return token;
        }
    }

    private boolean isUsable(OAuthToken token) {
        return token != null && token.expiresAt().isAfter(Instant.now().plusSeconds(30));
    }

    private void markFailure(PayPalOperationEntity operation, String status, String responseBody) {
        operation.setStatus(status);
        operation.setResponseBody(responseBody);
        operationRepository.saveAndFlush(operation);
    }

    private JsonNode readJson(String responseBody) throws IOException {
        if (responseBody == null || responseBody.isBlank()) {
            throw new IOException("PayPal returned an empty response.");
        }
        return objectMapper.readTree(responseBody);
    }

    private static String requiredText(JsonNode node, String field) throws IOException {
        String value = node == null ? "" : node.path(field).asText("").trim();
        if (value.isEmpty()) {
            throw new IOException("PayPal response is missing " + field + ".");
        }
        return value;
    }

    private static String status(JsonNode root, String fallback) {
        String value = root.path("status").asText("").trim();
        return value.isEmpty() ? fallback : value.toUpperCase(Locale.ROOT);
    }

    private static void putAmount(ObjectNode target, BigDecimal amount, String currency) {
        Objects.requireNonNull(amount, "amount");
        if (currency == null || currency.isBlank()) {
            throw new IllegalArgumentException("currency is required");
        }
        target.put("currency_code", currency.toUpperCase(Locale.ROOT));
        target.put("value", amount.toPlainString());
    }

    private static String requireProviderId(String providerId) {
        if (providerId == null || providerId.isBlank()) {
            throw new IllegalArgumentException("PayPal provider ID is required");
        }
        return providerId;
    }

    private static String pathSegment(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    private static boolean isSuccessful(int statusCode) {
        return statusCode >= 200 && statusCode < 300;
    }

    private static String header(Map<String, String> headers, String name) {
        if (headers == null) {
            return null;
        }
        return headers.entrySet().stream()
                .filter(entry -> entry.getKey() != null && entry.getKey().equalsIgnoreCase(name))
                .map(Map.Entry::getValue)
                .findFirst()
                .orElse(null);
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static String validateBaseUrl(String value) {
        try {
            String candidate = Objects.requireNonNull(value, "baseUrl").strip();
            URI uri = URI.create(candidate);
            String host = uri.getHost();
            boolean local = "localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host)
                    || "::1".equals(host) || "[::1]".equals(host);
            boolean sandbox = "api-m.sandbox.paypal.com".equalsIgnoreCase(host);
            boolean validScheme = local
                    ? "http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme())
                    : "https".equalsIgnoreCase(uri.getScheme()) && sandbox;
            if (!validScheme || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException("PayPal base URL must use HTTPS sandbox or a localhost test endpoint.");
            }
            return candidate.replaceAll("/+$", "");
        } catch (IllegalArgumentException | NullPointerException exception) {
            throw new IllegalArgumentException(
                    "PayPal base URL must use HTTPS sandbox or a localhost test endpoint.", exception);
        }
    }

    private static String requireConfiguration(String value, String description) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(description + " is not configured.");
        }
        return value;
    }

    private static ResponseStatusException badGateway(String detail, Throwable cause) {
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, detail, cause);
    }

    private record OAuthToken(String value, Instant expiresAt) {
    }

    @FunctionalInterface
    private interface RequestSender {
        HttpResponse<String> send(String requestId) throws IOException, InterruptedException;
    }

    @FunctionalInterface
    private interface ResponseParser {
        ProviderResult parse(String responseBody) throws IOException;
    }
}
