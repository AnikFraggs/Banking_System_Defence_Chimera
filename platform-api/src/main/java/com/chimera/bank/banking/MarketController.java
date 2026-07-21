package com.chimera.bank.banking;

import com.chimera.bank.auth.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/market")
public class MarketController {
    private final AuthService auth;
    private final MarketQuoteService market;

    public MarketController(AuthService auth, MarketQuoteService market) {
        this.auth = auth;
        this.market = market;
    }

    @GetMapping("/nifty")
    public MarketQuoteService.MarketQuote nifty(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return market.nifty();
    }

    // NEW: Full Market Overview Endpoint
    @GetMapping("/overview")
    public MarketQuoteService.MarketOverview overview(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return market.getOverview();
    }
}