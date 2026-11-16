package com.chimera.bank.ai;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiBrainClientTest {
    private HttpServer server;
    private volatile String requestPath;
    private volatile String requestBody;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void passesBrainCreditAssessmentThrough() throws Exception {
        startServer(200, """
                {"decision":"manual_review","requires_human_review":true,"auto_decline":false,
                 "fraud_probability":0.97,"red_flags":[{"id":"CB-PKG-01"}],"model_loaded":true}
                """);
        Map<String, Object> result = client(2000).scoreCreditApplication(Map.of("product", "auto_loan"));
        assertEquals("/v1/credit-application/score", requestPath);
        assertTrue(requestBody.contains("\"product\":\"auto_loan\""));
        assertEquals("manual_review", result.get("decision"));
        assertEquals(Boolean.FALSE, result.get("auto_decline"));
    }

    @Test
    void brainValidationErrorBecomesBadRequestWithoutEchoingInput() throws Exception {
        startServer(422, """
                {"detail":[{"type":"extra_forbidden","loc":["body","ssn"],"input":"000-00-0000"}]}
                """);
        ResponseStatusException e = assertThrows(ResponseStatusException.class,
                () -> client(2000).scoreCreditApplication(Map.of("ssn", "000-00-0000")));
        assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode());
        assertFalse(String.valueOf(e.getReason()).contains("000-00-0000"));
    }

    @Test
    void brainServerErrorFailsClosedToManualReview() throws Exception {
        startServer(500, "{}");
        Map<String, Object> result = client(2000).scoreCreditApplication(Map.of("product", "bnpl"));
        assertEquals("manual_review", result.get("decision"));
        assertEquals(Boolean.TRUE, result.get("from_fallback"));
        assertEquals(Boolean.FALSE, result.get("auto_decline"));
    }

    @Test
    void unreachableBrainFailsClosedToManualReview() {
        Map<String, Object> result = new AiBrainClient("http://127.0.0.1:1", 200, 200)
                .scoreCreditApplication(Map.of("product", "bnpl"));
        assertEquals("manual_review", result.get("decision"));
        assertEquals(Boolean.TRUE, result.get("requires_human_review"));
    }

    private AiBrainClient client(long readTimeoutMs) {
        return new AiBrainClient("http://127.0.0.1:" + server.getAddress().getPort(), 1000, readTimeoutMs);
    }

    private void startServer(int status, String body) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requestPath = exchange.getRequestURI().getPath();
            requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
    }
}
