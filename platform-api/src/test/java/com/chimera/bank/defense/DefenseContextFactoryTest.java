package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.defense.LayerVerdict;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.layers.L1_IpReputationLayer;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class DefenseContextFactoryTest {

    @Test
    void extractsFirstIpFromXForwardedFor() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Forwarded-For")).thenReturn("203.0.113.195, 10.0.0.1, 192.168.1.1");

        String ip = DefenseContextFactory.extractClientIp(request);
        assertEquals("203.0.113.195", ip);
    }

    @Test
    void fallsBackToXRealIpWhenXForwardedForMissing() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Forwarded-For")).thenReturn(null);
        when(request.getHeader("X-Real-IP")).thenReturn("198.51.100.22");

        String ip = DefenseContextFactory.extractClientIp(request);
        assertEquals("198.51.100.22", ip);
    }

    @Test
    void fallsBackToRemoteAddrWhenHeadersMissing() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Forwarded-For")).thenReturn(null);
        when(request.getHeader("X-Real-IP")).thenReturn(null);
        when(request.getRemoteAddr()).thenReturn("172.16.0.4");

        String ip = DefenseContextFactory.extractClientIp(request);
        assertEquals("172.16.0.4", ip);
    }

    @Test
    void fallsBackToLocalhostWhenRequestNull() {
        assertEquals("127.0.0.1", DefenseContextFactory.extractClientIp(null));
    }

    @Test
    void factoryCreatesDefenseContextWithExtractedIpAndFeedsL1Layer() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Forwarded-For")).thenReturn("10.0.1.55");

        String clientIp = DefenseContextFactory.extractClientIp(request);
        DefenseContextFactory factory = new DefenseContextFactory();
        DefenseContext ctx = factory.create("tx", clientIp, "CUST-1001", Role.CUSTOMER, "transfer", "payload");

        assertEquals("10.0.1.55", ctx.sourceIp());

        L1_IpReputationLayer l1 = new L1_IpReputationLayer();
        LayerVerdict verdict = l1.inspect(ctx);

        assertEquals(LayerVerdict.Decision.PASS, verdict.decision());
        assertTrue(Boolean.TRUE.equals(ctx.signals().get("private_network")));
        assertTrue(Boolean.TRUE.equals(ctx.signals().get("source_ip_seen")));
    }

    @Test
    void denylistedIpExtractedFromForwardedHeaderIsBlockedByL1() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Forwarded-For")).thenReturn("203.0.113.66, 127.0.0.1");

        String clientIp = DefenseContextFactory.extractClientIp(request);
        DefenseContextFactory factory = new DefenseContextFactory();
        DefenseContext ctx = factory.create("tx", clientIp, "CUST-1001", Role.CUSTOMER, "transfer", "payload");

        L1_IpReputationLayer l1 = new L1_IpReputationLayer();
        LayerVerdict verdict = l1.inspect(ctx);

        assertEquals(LayerVerdict.Decision.BLOCK, verdict.decision());
        assertEquals("denylisted_source_ip", verdict.reason());
    }
}
