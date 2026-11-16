package com.chimera.bank.payment;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class StubPayPalGatewayTest {
    @Mock
    private PayPalOperationRepository operationRepository;

    private StubPayPalGateway gateway;

    @BeforeEach
    void setUp() {
        when(operationRepository.saveAndFlush(any(PayPalOperationEntity.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        gateway = new StubPayPalGateway(operationRepository, new ObjectMapper());
    }

    @Test
    void returnsDeterministicSandboxLikeOutcomes() {
        UUID orderId = UUID.fromString("4b487f4d-9241-4c0f-96a6-c09c5c17c434");

        ProviderResult created = gateway.createOrder(orderId, new BigDecimal("12.50"), "USD", "Test order");
        assertEquals("CREATED", created.status());
        assertEquals("STUB-ORDER-" + orderId, created.providerId());

        ProviderResult fetched = gateway.getOrder(orderId, created.providerId());
        assertEquals("APPROVED", fetched.status());
        assertEquals(created.providerId(), fetched.providerId());

        ProviderResult authorized = gateway.authorizeOrder(
                orderId, created.providerId(), new BigDecimal("12.50"), "USD");
        assertEquals("COMPLETED", authorized.status());
        assertEquals("STUB-AUTH-" + created.providerId(), authorized.providerId());

        ProviderResult captured = gateway.captureAuthorization(
                orderId, authorized.providerId(), new BigDecimal("12.50"), "USD");
        assertEquals("COMPLETED", captured.status());
        assertEquals("STUB-CAPTURE-" + authorized.providerId(), captured.providerId());

        ProviderResult voided = gateway.voidAuthorization(orderId, authorized.providerId());
        assertEquals("VOIDED", voided.status());
        assertEquals(authorized.providerId(), voided.providerId());
        assertTrue(gateway.verifyWebhook("{}", Map.of()));
    }

    @Test
    void assignsFreshRequestIdToEveryLogicalOperation() {
        UUID orderId = UUID.randomUUID();
        gateway.createOrder(orderId, BigDecimal.TEN, "USD", "same request");
        gateway.createOrder(orderId, BigDecimal.TEN, "USD", "same request");

        ArgumentCaptor<PayPalOperationEntity> operations = ArgumentCaptor.forClass(PayPalOperationEntity.class);
        verify(operationRepository, times(4)).saveAndFlush(operations.capture());
        assertEquals(4, operations.getAllValues().size());
        assertEquals(2, operations.getAllValues().stream()
                .map(PayPalOperationEntity::getRequestId)
                .distinct()
                .count());
    }
}
