package com.chimera.bank.banking;

import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

class MarketQuoteServiceTest {

    @Test
    void fallbackWhenQuoteUrlBlankReturnsSimulatedQuotes() {
        MarketQuoteService service = new MarketQuoteService("", 2000);
        MarketQuoteService.MarketOverview overview = service.getOverview();

        assertNotNull(overview);
        assertNotNull(overview.assets());
        assertFalse(overview.assets().isEmpty());
        // All simulated quotes must have live == false
        for (MarketQuoteService.MarketQuote quote : overview.assets()) {
            assertFalse(quote.live(), "Simulated quote should not be marked as live: " + quote.symbol());
            assertEquals("Simulated Feed", quote.source());
        }
    }

    @Test
    void fallbackWhenRemoteFailsGracefullyReturnsSimulated() {
        RestClient restClient = mock(RestClient.class);
        RestClient.RequestHeadersUriSpec uriSpec = mock(RestClient.RequestHeadersUriSpec.class);
        RestClient.ResponseSpec responseSpec = mock(RestClient.ResponseSpec.class);

        when(restClient.get()).thenReturn(uriSpec);
        when(uriSpec.uri(anyString())).thenReturn(uriSpec);
        when(uriSpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.body(MarketQuoteService.RemoteQuoteFeed.class))
                .thenThrow(new RuntimeException("Connection timed out after 2000ms"));

        MarketQuoteService service = new MarketQuoteService(restClient, "http://unreachable-host:9999/quotes", 2000);
        MarketQuoteService.MarketOverview overview = service.getOverview();

        assertNotNull(overview);
        assertFalse(overview.assets().isEmpty());
        assertFalse(overview.assets().get(0).live());
    }

    @Test
    void fallbackWhenRemoteReturnsEmptyQuotes() {
        RestClient restClient = mock(RestClient.class);
        RestClient.RequestHeadersUriSpec uriSpec = mock(RestClient.RequestHeadersUriSpec.class);
        RestClient.ResponseSpec responseSpec = mock(RestClient.ResponseSpec.class);

        when(restClient.get()).thenReturn(uriSpec);
        when(uriSpec.uri(anyString())).thenReturn(uriSpec);
        when(uriSpec.retrieve()).thenReturn(responseSpec);
        // Returns feed with empty quotes
        when(responseSpec.body(MarketQuoteService.RemoteQuoteFeed.class))
                .thenReturn(new MarketQuoteService.RemoteQuoteFeed(List.of(), List.of(), "4.0% p.a."));

        MarketQuoteService service = new MarketQuoteService(restClient, "http://fake-host/quotes", 2000);
        MarketQuoteService.MarketOverview overview = service.getOverview();

        assertNotNull(overview);
        assertFalse(overview.assets().isEmpty());
        assertFalse(overview.assets().get(0).live());
    }

    @Test
    void liveQuotesReturnedWhenRemoteSucceeds() {
        RestClient restClient = mock(RestClient.class);
        RestClient.RequestHeadersUriSpec uriSpec = mock(RestClient.RequestHeadersUriSpec.class);
        RestClient.ResponseSpec responseSpec = mock(RestClient.ResponseSpec.class);

        when(restClient.get()).thenReturn(uriSpec);
        when(uriSpec.uri(anyString())).thenReturn(uriSpec);
        when(uriSpec.retrieve()).thenReturn(responseSpec);

        List<MarketQuoteService.MarketQuote> remoteQuotes = List.of(
                new MarketQuoteService.MarketQuote("NIFTY 50", 24500.0, null, "Live NSE Feed", true, "Live market data")
        );
        when(responseSpec.body(MarketQuoteService.RemoteQuoteFeed.class))
                .thenReturn(new MarketQuoteService.RemoteQuoteFeed(remoteQuotes, null, "7.0% p.a."));

        MarketQuoteService service = new MarketQuoteService(restClient, "http://live-host/quotes", 2000);
        MarketQuoteService.MarketOverview overview = service.getOverview();

        assertNotNull(overview);
        assertEquals(1, overview.assets().size());
        assertTrue(overview.assets().get(0).live());
        assertEquals("Live market data", overview.assets().get(0).message());
    }
}
