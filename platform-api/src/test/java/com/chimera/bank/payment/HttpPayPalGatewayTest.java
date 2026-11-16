package com.chimera.bank.payment;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class HttpPayPalGatewayTest {
    private final UUID orderId = UUID.randomUUID();
    private PayPalOperationRepository operationRepository;
    private HttpPayPalGateway gateway;

    @BeforeEach
    void setUp() {
        operationRepository = mock(PayPalOperationRepository.class);
        gateway = new HttpPayPalGateway(operationRepository, new ObjectMapper(), "http://127.0.0.1:1",
                "client", "secret", "", Duration.ofSeconds(1), Duration.ofSeconds(1));
    }

    @Test
    void unknownCaptureRequiresReconciliationBeforeRetry() {
        assertRetryBlocked("UNKNOWN", () -> gateway.captureAuthorization(
                orderId, "AUTH-1", BigDecimal.TEN, "USD"));
    }

    @Test
    void pendingCaptureRequiresReconciliationBeforeRetry() {
        assertRetryBlocked("PENDING", () -> gateway.captureAuthorization(
                orderId, "AUTH-1", BigDecimal.TEN, "USD"));
    }

    @Test
    void unknownVoidRequiresReconciliationBeforeRetry() {
        assertRetryBlocked("UNKNOWN", () -> gateway.voidAuthorization(orderId, "AUTH-1"));
    }

    @Test
    void pendingVoidRequiresReconciliationBeforeRetry() {
        assertRetryBlocked("PENDING", () -> gateway.voidAuthorization(orderId, "AUTH-1"));
    }

    private void assertRetryBlocked(String operationStatus, Executable retry) {
        PayPalOperationEntity operation = new PayPalOperationEntity();
        operation.setOrderId(orderId);
        operation.setOperationType("CAPTURE_AUTHORIZATION");
        operation.setRequestId(UUID.randomUUID().toString());
        operation.setRequestBody("{}");
        operation.setRequestBodyHash("hash");
        operation.setStatus(operationStatus);
        operation.setCreatedAt(Instant.now());
        operation.setUpdatedAt(Instant.now());
        when(operationRepository
                .findFirstByOperationTypeAndOrderIdAndRequestBodyHashAndStatusInOrderByCreatedAtDesc(
                        anyString(), eq(orderId), anyString(), anyCollection()))
                .thenReturn(Optional.of(operation));

        ResponseStatusException error = assertThrows(ResponseStatusException.class, retry);
        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(operationRepository, never()).saveAndFlush(any());
    }
}
