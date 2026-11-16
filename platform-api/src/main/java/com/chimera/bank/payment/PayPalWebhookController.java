package com.chimera.bank.payment;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/webhooks/paypal")
public class PayPalWebhookController {
    private final PayPalWebhookService webhooks;

    public PayPalWebhookController(PayPalWebhookService webhooks) {
        this.webhooks = webhooks;
    }

    @PostMapping
    public ResponseEntity<Map<String, String>> receive(@RequestBody String rawBody,
                                                       @RequestHeader Map<String, String> headers) {
        PayPalWebhookService.Result result = webhooks.process(rawBody, headers);
        if (result == PayPalWebhookService.Result.INVALID) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of("status", "INVALID"));
        }
        return ResponseEntity.accepted().body(Map.of("status", result.name()));
    }
}
