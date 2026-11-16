package com.chimera.bank.audit;

import com.chimera.bank.checkout.CheckoutOrderEntity;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class ReceiptService {
    private final ReceiptRepository repository;
    private final AuditCrypto crypto;
    private final ObjectMapper objectMapper;

    public ReceiptService(ReceiptRepository repository, AuditCrypto crypto, ObjectMapper objectMapper) {
        this.repository = repository;
        this.crypto = crypto;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public ReceiptEntity issue(CheckoutOrderEntity order) {
        return repository.findByOrderId(order.getId()).orElseGet(() -> {
            try {
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("orderId", order.getId().toString());
                payload.put("paypalOrderId", order.getPaypalOrderId());
                payload.put("paypalAuthorizationId", order.getPaypalAuthorizationId());
                payload.put("captureId", order.getCaptureId());
                payload.put("amount", order.getAmount());
                payload.put("currency", order.getCurrency());
                payload.put("state", order.getState().name());
                payload.put("score", order.getScore());
                payload.put("issuedAt", order.getUpdatedAt());
                String canonical = objectMapper.writeValueAsString(payload);
                ReceiptEntity receipt = new ReceiptEntity();
                receipt.setOrderId(order.getId());
                receipt.setPayload(canonical);
                receipt.setSignature(crypto.hmac(canonical));
                receipt.setKeyVersion(crypto.keyVersion());
                return repository.save(receipt);
            } catch (Exception e) {
                throw new IllegalStateException("Could not issue signed receipt", e);
            }
        });
    }

    public boolean verify(ReceiptEntity receipt) {
        return crypto.validSignature(receipt.getPayload(), receipt.getSignature());
    }
}
