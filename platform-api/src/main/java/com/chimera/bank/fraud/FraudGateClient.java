package com.chimera.bank.fraud;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;

@Component
@ConditionalOnProperty(prefix = "chimera.checkout.fraud-gate", name = "transport", havingValue = "http")
public class FraudGateClient implements FraudGateTransport {
    private final URI scoreUri;
    private final Duration timeout;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public FraudGateClient(
            @Value("${chimera.checkout.fraud-gate.base-url:http://localhost:8001}") String baseUrl,
            @Value("${chimera.checkout.fraud-gate.timeout-ms:300}") long timeoutMs,
            ObjectMapper objectMapper) {
        this.scoreUri = URI.create(baseUrl.replaceAll("/$", "") + "/score/pre-capture");
        this.timeout = Duration.ofMillis(timeoutMs);
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(timeout)
                .build();
    }

    @Override
    public ScoreResponse score(ScoreRequest request) {
        long started = System.nanoTime();
        try {
            HttpRequest httpRequest = HttpRequest.newBuilder(scoreUri)
                    .timeout(timeout)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(request)))
                    .build();
            HttpResponse<String> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                return fallback("GATE_ERROR", "Fraud gate returned HTTP " + response.statusCode(), elapsed(started));
            }
            ScoreResponse scored = objectMapper.readValue(response.body(), ScoreResponse.class);
            if (!scored.valid()) {
                return fallback("GATE_ERROR", "Fraud gate returned an invalid decision", elapsed(started));
            }
            return scored;
        } catch (java.net.http.HttpTimeoutException e) {
            return fallback("GATE_TIMEOUT", "Fraud gate exceeded its decision budget", elapsed(started));
        } catch (Exception e) {
            return fallback("GATE_ERROR", "Fraud gate is unavailable; verification is required", elapsed(started));
        }
    }

    private ScoreResponse fallback(String code, String message, double latencyMs) {
        return FraudGateFallback.challenge(code, message, latencyMs);
    }

    private double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }
}
