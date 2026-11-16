package com.chimera.bank.checkout;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.InputStream;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;

/**
 * Optional bounded L5-only HTTP generator. Invalid, oversized, slow, or
 * semantically inconsistent output always falls back to the deterministic prompt.
 */
@Component
@ConditionalOnProperty(prefix = "chimera.checkout.step-up", name = "generator", havingValue = "http")
public final class HttpVerificationChallengeGenerator implements VerificationChallengeGenerator {
    private static final int MAX_RESPONSE_BYTES = 16_384;
    private static final int MAX_PROMPT_CHARS = 1_000;

    private final ObjectMapper objectMapper;
    private final DeterministicVerificationChallengeGenerator fallback =
            new DeterministicVerificationChallengeGenerator();
    private final String httpUrl;
    private final String apiKey;
    private final Duration timeout;
    private final HttpClient client;

    public HttpVerificationChallengeGenerator(
            ObjectMapper objectMapper,
            @Value("${chimera.checkout.step-up.http-url:}") String httpUrl,
            @Value("${chimera.checkout.step-up.http-api-key:}") String apiKey,
            @Value("${chimera.checkout.step-up.http-timeout-ms:500}") long timeoutMs) {
        this.objectMapper = objectMapper;
        this.apiKey = apiKey == null ? "" : apiKey;
        this.timeout = Duration.ofMillis(Math.max(50, Math.min(2_000, timeoutMs)));
        this.httpUrl = httpUrl == null ? "" : httpUrl;
        this.client = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(this.timeout)
                .build();
    }

    @Override
    public GeneratedChallenge generate(UUID orderId, InvoiceDiscrepancy discrepancy) {
        GeneratedChallenge deterministic = fallback.generate(orderId, discrepancy);
        if (httpUrl.isBlank()) return deterministic;
        try {
            URI endpoint = URI.create(httpUrl);
            String body = objectMapper.writeValueAsString(Map.of(
                    "order_id", orderId.toString(),
                    "order_amount", discrepancy.orderAmountText(),
                    "invoice_amount", discrepancy.invoiceAmountText(),
                    "currency", discrepancy.currency(),
                    "response_format", "strict_json_prompt_and_expected_answer"));
            HttpRequest.Builder builder = HttpRequest.newBuilder(endpoint)
                    .timeout(timeout)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
            if (!apiKey.isBlank()) builder.header("Authorization", "Bearer " + apiKey);
            HttpResponse<InputStream> response = client.send(builder.build(),
                    HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() != 200) return deterministic;
            byte[] payload;
            try (InputStream input = response.body()) {
                payload = input.readNBytes(MAX_RESPONSE_BYTES + 1);
            }
            if (payload.length > MAX_RESPONSE_BYTES) return deterministic;
            JsonNode root = objectMapper.readTree(payload);
            if (root == null || !root.isObject() || root.size() != 2
                    || !root.path("prompt").isTextual() || !root.path("expected_answer").isTextual()) {
                return deterministic;
            }
            String prompt = root.path("prompt").textValue();
            String answer = root.path("expected_answer").textValue();
            if (!validPrompt(prompt, orderId, discrepancy) || !correctAnswer(answer, deterministic.expectedAnswer())) {
                return deterministic;
            }
            return new GeneratedChallenge(prompt, deterministic.expectedAnswer());
        } catch (Exception e) {
            return deterministic;
        }
    }

    private static boolean validPrompt(String prompt, UUID orderId, InvoiceDiscrepancy discrepancy) {
        return prompt != null && !prompt.isBlank() && prompt.length() <= MAX_PROMPT_CHARS
                && prompt.contains(orderId.toString())
                && prompt.contains(discrepancy.orderAmountText())
                && prompt.contains(discrepancy.invoiceAmountText())
                && prompt.chars().noneMatch(character -> Character.isISOControl(character)
                        && !Character.isWhitespace(character));
    }

    private static boolean correctAnswer(String candidate, String expected) {
        if (candidate == null || candidate.length() > 32 || !candidate.matches("-?[0-9]+\\.[0-9]{2}")) {
            return false;
        }
        try {
            return new BigDecimal(candidate).compareTo(new BigDecimal(expected)) == 0;
        } catch (NumberFormatException e) {
            return false;
        }
    }
}
