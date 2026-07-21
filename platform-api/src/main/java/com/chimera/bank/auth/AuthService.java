package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Deliberately small, local-only identity service for the reference app.
 * Production deployments must replace this with OIDC/SSO, hashed credentials,
 * MFA, secure cookies, persistent audit storage, and server-side revocation.
 */
@Service
public class AuthService {

    public record LoginRequest(String username, String password, String role, String authKey) { }
    public record SessionView(String token, String registrationNumber, String displayName,
                              String role, Instant expiresAt) { }
    public record Principal(String registrationNumber, String displayName, Role role,
                            Instant expiresAt) { }

    private record DemoUser(String username, String password, String registrationNumber,
                            String displayName, Role role) { }

    private static final Map<String, DemoUser> DEMO_USERS = Map.of(
            "client", new DemoUser("client", "demo-pass", "CUST-1001", "Anita Rao", Role.CUSTOMER),
            "accountant", new DemoUser("accountant", "demo-pass", "ACC-001", "Dev Mehta", Role.ACCOUNTANT),
            "manager", new DemoUser("manager", "demo-pass", "MGR-ROOT", "Maya Sen", Role.MANAGER));

    private final Map<String, Principal> sessions = new ConcurrentHashMap<>();
    private final byte[] managerAuthKey;

    public AuthService(@Value("${chimera.auth.manager.key:manager-local-key}") String managerAuthKey) {
        this.managerAuthKey = (managerAuthKey == null ? "" : managerAuthKey).getBytes(StandardCharsets.UTF_8);
    }

    public SessionView login(LoginRequest request) {
        if (request == null || request.username() == null || request.password() == null || request.role() == null) {
            throw unauthorized("Username, password, and role are required.");
        }
        DemoUser user = DEMO_USERS.get(request.username().trim().toLowerCase());
        Role requestedRole = parseRole(request.role());
        if (user == null || !user.password().equals(request.password()) || user.role() != requestedRole) {
            throw unauthorized("Invalid credentials or role.");
        }
        if (requestedRole == Role.MANAGER && !managerKeyMatches(request.authKey())) {
            throw unauthorized("A valid manager authorization key is required.");
        }
        Instant expiresAt = Instant.now().plusSeconds(8 * 60 * 60);
        Principal principal = new Principal(user.registrationNumber(), user.displayName(), user.role(), expiresAt);
        String token = UUID.randomUUID().toString();
        sessions.put(token, principal);
        return new SessionView(token, principal.registrationNumber(), principal.displayName(),
                principal.role().name(), expiresAt);
    }

    public Principal require(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw unauthorized("Sign in is required.");
        }
        String token = authorization.substring("Bearer ".length()).trim();
        Principal principal = sessions.get(token);
        if (principal == null || principal.expiresAt().isBefore(Instant.now())) {
            sessions.remove(token);
            throw unauthorized("Your local session has expired. Please sign in again.");
        }
        return principal;
    }

    public Principal requireOneOf(String authorization, Role... roles) {
        Principal principal = require(authorization);
        for (Role role : roles) {
            if (principal.role() == role) {
                return principal;
            }
        }
        throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Your role is not permitted for this action.");
    }

    private boolean managerKeyMatches(String presented) {
        return MessageDigest.isEqual(managerAuthKey,
                (presented == null ? "" : presented).getBytes(StandardCharsets.UTF_8));
    }

    private static Role parseRole(String role) {
        try {
            return Role.valueOf(role.trim().toUpperCase());
        } catch (RuntimeException e) {
            throw unauthorized("Unknown role.");
        }
    }

    private static ResponseStatusException unauthorized(String message) {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, message);
    }
}