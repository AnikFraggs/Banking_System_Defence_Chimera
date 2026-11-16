package com.chimera.bank.checkout;

import java.math.BigDecimal;
import java.util.Objects;

/** Exact, simulated invoice values used only by the post-authorization L5 challenge. */
public record InvoiceDiscrepancy(BigDecimal orderAmount, BigDecimal invoiceAmount, String currency) {
    public InvoiceDiscrepancy {
        Objects.requireNonNull(orderAmount, "orderAmount");
        Objects.requireNonNull(invoiceAmount, "invoiceAmount");
        Objects.requireNonNull(currency, "currency");
        orderAmount = orderAmount.stripTrailingZeros();
        invoiceAmount = invoiceAmount.stripTrailingZeros();
        if (!currency.matches("[A-Z]{3}")) throw new IllegalArgumentException("Invalid invoice currency");
    }

    public BigDecimal signedDifference() {
        return invoiceAmount.subtract(orderAmount).setScale(2);
    }

    public String orderAmountText() {
        return orderAmount.setScale(2).toPlainString();
    }

    public String invoiceAmountText() {
        return invoiceAmount.setScale(2).toPlainString();
    }

    String binding() {
        return currency + ":" + orderAmountText() + ":" + invoiceAmountText();
    }
}
