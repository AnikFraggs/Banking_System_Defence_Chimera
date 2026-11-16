package com.chimera.bank.payment;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Map;

@Service
public class PayPalWebhookService {
    public enum Result {PROCESSED, DUPLICATE, INVALID}

    private final PayPalGateway payPalGateway;
    private final WebhookEventRepository eventRepository;
    private final ObjectMapper objectMapper;

    public PayPalWebhookService(PayPalGateway payPalGateway, WebhookEventRepository eventRepository,
                                ObjectMapper objectMapper) {
        this.payPalGateway = payPalGateway;
        this.eventRepository = eventRepository;
        this.objectMapper = objectMapper;
    }

    public Result process(String rawBody, Map<String, String> headers) {
        if (!payPalGateway.verifyWebhook(rawBody, headers)) {
            return Result.INVALID;
        }

        JsonNode event;
        try {
            event = objectMapper.readTree(rawBody);
        } catch (JsonProcessingException | IllegalArgumentException exception) {
            return Result.INVALID;
        }

        String eventId = event.path("id").asText("").trim();
        if (eventId.isEmpty()) {
            return Result.INVALID;
        }
        String eventType = event.path("event_type").asText("");
        String payloadHash = PayPalRequestSupport.sha256(rawBody);

        if (eventRepository.existsById(eventId)) {
            return Result.DUPLICATE;
        }

        WebhookEventEntity verifiedEvent = new WebhookEventEntity(
                eventId, eventType, payloadHash, Instant.now());
        try {
            eventRepository.saveAndFlush(verifiedEvent);
            return Result.PROCESSED;
        } catch (DataIntegrityViolationException exception) {
            // The primary key makes concurrent delivery deduplication atomic.
            return Result.DUPLICATE;
        }
    }
}
