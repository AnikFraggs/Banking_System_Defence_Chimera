package com.chimera.bank.payment;

public record ProviderResult(String providerId, String status, String responseBody) {
}
