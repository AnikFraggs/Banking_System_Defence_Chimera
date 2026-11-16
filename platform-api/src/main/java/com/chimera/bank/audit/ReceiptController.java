package com.chimera.bank.audit;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.checkout.CheckoutService;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

@RestController
@RequestMapping("/api/receipts")
public class ReceiptController {
    private final ReceiptRepository receipts;
    private final ReceiptService receiptService;
    private final CheckoutService checkout;
    private final AuthService auth;

    public ReceiptController(ReceiptRepository receipts, ReceiptService receiptService,
                             CheckoutService checkout, AuthService auth) {
        this.receipts = receipts;
        this.receiptService = receiptService;
        this.checkout = checkout;
        this.auth = auth;
    }

    // The @Lob payload is a PostgreSQL large object, which can only be streamed inside a transaction.
    @Transactional(readOnly = true)
    @GetMapping("/{orderId}")
    public ReceiptView get(@RequestHeader(value = "Authorization", required = false) String authorization,
                           @PathVariable UUID orderId) {
        AuthService.Principal principal = auth.require(authorization);
        checkout.get(principal, orderId);
        ReceiptEntity receipt = receipts.findByOrderId(orderId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Receipt is not available"));
        return new ReceiptView(receipt.getPayload(), receipt.getSignature(), receipt.getKeyVersion(),
                receiptService.verify(receipt));
    }

    public record ReceiptView(String payload, String signature, String keyVersion, boolean valid) {}
}
