package com.chimera.bank.checkout;

import com.chimera.bank.fraud.FraudGateClient;
import com.chimera.bank.fraud.ScoreRequest;
import com.chimera.bank.fraud.ScoreResponse;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FraudGateClientTest {
    private HttpServer server;
    private volatile String upgradeHeader;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void parsesValidDecision() throws Exception {
        startServer(200, """
                {"decision_id":"d1","score":0.1,"action":"CAPTURE","reasons":[],"component_scores":{},"model_version":"test","feature_hash":"abc","fallback":false,"latency_ms":4}
                """, 0);
        FraudGateClient client = client(2000);
        ScoreResponse response = client.score(request());
        assertEquals("CAPTURE", response.action());
        assertEquals(0.1, response.score());
        assertNull(upgradeHeader);
    }

    @Test
    void timeoutFailsClosedToChallenge() throws Exception {
        startServer(200, "{}", 150);
        FraudGateClient client = client(40);
        ScoreResponse response = client.score(request());
        assertEquals("CHALLENGE", response.action());
        assertEquals("GATE_TIMEOUT", response.reasons().get(0).code());
        assertTrue(response.fallback());
    }

    @Test
    void serializesFastApiTelemetryContract() throws Exception {
        ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        JsonNode payload = mapper.readTree(mapper.writeValueAsString(request()));
        JsonNode movement = payload.path("telemetry").path("mouse_movements").path(0);
        assertEquals(4.0, movement.path("x").asDouble());
        assertEquals(5.0, movement.path("y").asDouble());
        assertEquals(6.0, movement.path("interval_ms").asDouble());
        assertTrue(movement.has("interval_ms"));
        assertTrue(payload.path("timestamp").isTextual());
        assertTrue(payload.path("history").path(0).path("timestamp").isTextual());
    }

    private FraudGateClient client(long timeoutMs) {
        return new FraudGateClient("http://127.0.0.1:" + server.getAddress().getPort(), timeoutMs,
                new ObjectMapper().registerModule(new JavaTimeModule()));
    }

    private void startServer(int status, String body, long delayMs) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/score/pre-capture", exchange -> {
            try {
                upgradeHeader = exchange.getRequestHeaders().getFirst("Upgrade");
                if (delayMs > 0) Thread.sleep(delayMs);
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(status, bytes.length);
                exchange.getResponseBody().write(bytes);
                exchange.close();
            } catch (Exception ignored) {
            }
        });
        server.start();
    }

    private ScoreRequest request() {
        return new ScoreRequest("order", null, "INITIAL", BigDecimal.TEN, "USD", Instant.now(), "CARD",
                null, new ScoreRequest.Telemetry(List.of(120.0), List.of(),
                List.of(new ScoreRequest.MouseMovement(4.0, 5.0, 6.0))),
                List.of(new ScoreRequest.HistoryEvent("device", "destination", BigDecimal.ONE, Instant.now())),
                null, null);
    }
}
