package com.chimera.bank.payment;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PayPalWebhookServiceTest {
    private static final String RAW_EVENT = "{\"id\":\"WH-EVENT-1\",\"event_type\":\"PAYMENT.CAPTURE.COMPLETED\"}";

    @Mock
    private PayPalGateway payPalGateway;
    @Mock
    private WebhookEventRepository eventRepository;

    private PayPalWebhookService service;

    @BeforeEach
    void setUp() {
        service = new PayPalWebhookService(payPalGateway, eventRepository, new ObjectMapper());
    }

    @Test
    void persistsVerifiedEventAndDoesNotMoveMoney() throws Exception {
        when(payPalGateway.verifyWebhook(RAW_EVENT, Map.of())).thenReturn(true);
        when(eventRepository.existsById("WH-EVENT-1")).thenReturn(false);
        when(eventRepository.saveAndFlush(any(WebhookEventEntity.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        PayPalWebhookService.Result result = service.process(RAW_EVENT, Map.of());

        assertEquals(PayPalWebhookService.Result.PROCESSED, result);
        ArgumentCaptor<WebhookEventEntity> event = ArgumentCaptor.forClass(WebhookEventEntity.class);
        verify(eventRepository).saveAndFlush(event.capture());
        assertEquals("WH-EVENT-1", event.getValue().getEventId());
        assertEquals("PAYMENT.CAPTURE.COMPLETED", event.getValue().getEventType());
        assertEquals(sha256(RAW_EVENT), event.getValue().getPayloadHash());
        assertNotNull(event.getValue().getProcessedAt());
        verify(payPalGateway).verifyWebhook(RAW_EVENT, Map.of());
        verifyNoMoreInteractions(payPalGateway);
    }

    @Test
    void returnsDuplicateForPreviouslyProcessedEvent() {
        when(payPalGateway.verifyWebhook(RAW_EVENT, Map.of())).thenReturn(true);
        when(eventRepository.existsById("WH-EVENT-1")).thenReturn(true);

        assertEquals(PayPalWebhookService.Result.DUPLICATE, service.process(RAW_EVENT, Map.of()));
        verify(eventRepository, never()).saveAndFlush(any());
    }

    @Test
    void catchesConcurrentInsertAsDuplicate() {
        when(payPalGateway.verifyWebhook(RAW_EVENT, Map.of())).thenReturn(true);
        when(eventRepository.existsById("WH-EVENT-1")).thenReturn(false);
        when(eventRepository.saveAndFlush(any(WebhookEventEntity.class)))
                .thenThrow(new DataIntegrityViolationException("duplicate event"));

        assertEquals(PayPalWebhookService.Result.DUPLICATE, service.process(RAW_EVENT, Map.of()));
    }

    @Test
    void rejectsInvalidSignatureBeforeInspectingRepository() {
        when(payPalGateway.verifyWebhook(RAW_EVENT, Map.of())).thenReturn(false);

        assertEquals(PayPalWebhookService.Result.INVALID, service.process(RAW_EVENT, Map.of()));
        verifyNoInteractions(eventRepository);
    }

    @Test
    void rejectsVerifiedPayloadWithoutEventId() {
        String payload = "{\"event_type\":\"PAYMENT.CAPTURE.COMPLETED\"}";
        when(payPalGateway.verifyWebhook(payload, Map.of())).thenReturn(true);

        assertEquals(PayPalWebhookService.Result.INVALID, service.process(payload, Map.of()));
        verifyNoInteractions(eventRepository);
    }

    private static String sha256(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
