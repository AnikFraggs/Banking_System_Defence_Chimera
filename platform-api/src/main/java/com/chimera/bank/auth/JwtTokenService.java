package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Optional;

/**
 * Optional OAuth2/OIDC JWT validation. Active only when an issuer or JWK set is configured; the
 * local demo session flow keeps working when it is absent. A valid JWT is mapped to the same
 * {@link AuthService.Principal} used by the rest of the platform, so RBAC is unchanged.
 */
@Component
@ConditionalOnProperty(name = "chimera.auth.jwt.enabled", havingValue = "true")
public class JwtTokenService {
    private final JwtDecoder decoder;
    private final String roleClaim;

    public JwtTokenService(@Value("${chimera.auth.jwt.jwk-set-uri:}") String jwkSetUri,
                           @Value("${chimera.auth.jwt.issuer-uri:}") String issuerUri,
                           @Value("${chimera.auth.jwt.role-claim:role}") String roleClaim) {
        if (!jwkSetUri.isBlank()) {
            NimbusJwtDecoder jwkDecoder = NimbusJwtDecoder.withJwkSetUri(jwkSetUri).build();
            if (!issuerUri.isBlank()) {
                jwkDecoder.setJwtValidator(JwtValidators.createDefaultWithIssuer(issuerUri));
            }
            this.decoder = jwkDecoder;
        } else if (!issuerUri.isBlank()) {
            this.decoder = NimbusJwtDecoder.withIssuerLocation(issuerUri).build();
        } else {
            throw new IllegalStateException("chimera.auth.jwt.enabled=true requires jwk-set-uri or issuer-uri");
        }
        this.roleClaim = roleClaim;
    }

    public Optional<AuthService.Principal> authenticate(String token) {
        try {
            Jwt jwt = decoder.decode(token);
            String username = jwt.getSubject();
            String roleText = roleClaim(jwt);
            if (username == null || roleText == null) return Optional.empty();
            String normalizedRole = roleText.trim().toUpperCase();
            if (normalizedRole.startsWith("ROLE_")) normalizedRole = normalizedRole.substring(5);
            Role role = Role.valueOf(normalizedRole);
            Instant expiresAt = jwt.getExpiresAt() == null ? Instant.now().plusSeconds(3600) : jwt.getExpiresAt();
            String displayName = jwt.getClaimAsString("name") == null ? username : jwt.getClaimAsString("name");
            return Optional.of(new AuthService.Principal(username, displayName, role, expiresAt));
        } catch (JwtException | IllegalArgumentException e) {
            return Optional.empty();
        }
    }

    private String roleClaim(Jwt jwt) {
        Object claim = jwt.getClaims().get(roleClaim);
        if (claim instanceof String value) return value;
        if (claim instanceof java.util.Collection<?> values) {
            for (Object value : values) {
                if (value instanceof String text && isSupportedRole(text)) return text;
            }
        }
        return null;
    }

    private boolean isSupportedRole(String roleText) {
        String normalized = roleText.trim().toUpperCase();
        if (normalized.startsWith("ROLE_")) normalized = normalized.substring(5);
        try {
            Role.valueOf(normalized);
            return true;
        } catch (IllegalArgumentException ignored) {
            return false;
        }
    }
}
