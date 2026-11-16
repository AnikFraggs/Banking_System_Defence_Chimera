package com.chimera.bank.defense;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.rbac.Role;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Instant;
import java.util.UUID;

/**
 * Centralized factory for constructing {@link DefenseContext} instances with
 * real client IP extraction across Nginx proxies (X-Forwarded-For / X-Real-IP).
 */
@Component
public class DefenseContextFactory {

    public DefenseContext create(String prefix, String registrationNumber, Role role, String purpose, String payload) {
        String clientIp = resolveClientIp();
        return new DefenseContext(
                prefix + "-" + UUID.randomUUID(),
                Instant.now(),
                clientIp,
                registrationNumber,
                role,
                purpose,
                payload
        );
    }

    public DefenseContext create(String prefix, String explicitIp, String registrationNumber, Role role, String purpose, String payload) {
        String clientIp = (explicitIp != null && !explicitIp.isBlank()) ? explicitIp : resolveClientIp();
        return new DefenseContext(
                prefix + "-" + UUID.randomUUID(),
                Instant.now(),
                clientIp,
                registrationNumber,
                role,
                purpose,
                payload
        );
    }

    public static String resolveClientIp() {
        if (RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attrs) {
            return extractClientIp(attrs.getRequest());
        }
        return "127.0.0.1";
    }

    public static String extractClientIp(HttpServletRequest request) {
        if (request == null) {
            return "127.0.0.1";
        }
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            String first = forwarded.split(",")[0].trim();
            if (!first.isEmpty()) {
                return first;
            }
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        String remote = request.getRemoteAddr();
        if (remote != null && !remote.isBlank()) {
            return remote.trim();
        }
        return "127.0.0.1";
    }
}
