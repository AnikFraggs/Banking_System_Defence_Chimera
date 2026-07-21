package com.chimera.bank.banking;

import org.springframework.stereotype.Service;
import java.time.Instant;
import java.util.List;

@Service
public class MarketQuoteService {
    public record MarketQuote(String symbol, Double price, Instant asOf, String source, boolean live, String message) { }
    public record MarketOverview(List<MarketQuote> assets, String bankInterestRate) { }

    // In production, replace this with a real API call (e.g., Alpha Vantage, Yahoo Finance)
    public MarketOverview getOverview() {
        Instant now = Instant.now();
        return new MarketOverview(
            List.of(
                new MarketQuote("NIFTY 50", 22350.45, now, "Simulated Feed", true, "Live market data"),
                new MarketQuote("GOLD (10g)", 74250.00, now, "Simulated Feed", true, "MCX rates"),
                new MarketQuote("USD / INR", 83.45, now, "Simulated Feed", true, "Forex rates"),
                new MarketQuote("HDFC BANK", 1502.30, now, "Simulated Feed", true, "Equity"),
                new MarketQuote("BTC / INR", 6250000.00, now, "Simulated Feed", true, "Crypto")
            ),
            "3.50% p.a. (Savings) | 8.40% p.a. (Fixed Deposit)"
        );
    }
    
    // Keep existing method for backward compatibility
    public MarketQuote nifty() {
        return getOverview().assets().get(0);
    }
}