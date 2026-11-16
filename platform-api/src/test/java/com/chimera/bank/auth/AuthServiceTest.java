package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthServiceTest {
    private UserRepository userRepository;
    @SuppressWarnings("unchecked")
    private final ObjectProvider<JwtTokenService> jwtProvider = mock(ObjectProvider.class);
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
    private AuthService auth;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        auth = new AuthService("manager-local-key", userRepository, jwtProvider);
        when(userRepository.findByUsername("client")).thenReturn(Optional.of(user("client", "CUSTOMER", "CUST-1001")));
        when(userRepository.findByUsername("manager")).thenReturn(Optional.of(user("manager", "MANAGER", "MGR-ROOT")));
    }

    private AppUser user(String username, String role, String regNo) {
        AppUser u = new AppUser();
        u.setUsername(username);
        u.setPassword(passwordEncoder.encode("demo-pass"));
        u.setRole(role);
        u.setRegistrationNumber(regNo);
        u.setCustomerName("Test User");
        u.setAccountNumber("CHM-TEST");
        u.setBalance(0.0);
        return u;
    }

    private String loginToken(String username, String role, String authKey) {
        return auth.login(new AuthService.LoginRequest(username, "demo-pass", role, authKey)).token();
    }

    @Test
    void localSessionLoginAndRequire() {
        String token = loginToken("client", "CUSTOMER", null);
        AuthService.Principal principal = auth.require("Bearer " + token);
        assertEquals("client", principal.registrationNumber());
        assertEquals(Role.CUSTOMER, principal.role());
    }

    @Test
    void requireRejectsMissingOrMalformedHeader() {
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> auth.require(null)).getStatusCode());
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> auth.require("Basic abc")).getStatusCode());
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> auth.require("Bearer unknown-token")).getStatusCode());
    }

    @Test
    void jwtIsRoutedToDecoderWhenEnabled() {
        JwtTokenService jwt = mock(JwtTokenService.class);
        when(jwtProvider.getIfAvailable()).thenReturn(jwt);
        AuthService.Principal expected = new AuthService.Principal("oidc-user", "OIDC User",
                Role.MANAGER, Instant.now().plusSeconds(3600));
        when(jwt.authenticate("a.b.c")).thenReturn(Optional.of(expected));
        AuthService.Principal principal = auth.require("Bearer a.b.c");
        assertEquals("oidc-user", principal.registrationNumber());
        assertEquals(Role.MANAGER, principal.role());
        verify(jwt).authenticate("a.b.c");
    }

    @Test
    void invalidJwtIsRejected() {
        JwtTokenService jwt = mock(JwtTokenService.class);
        when(jwtProvider.getIfAvailable()).thenReturn(jwt);
        when(jwt.authenticate(anyString())).thenReturn(Optional.empty());
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> auth.require("Bearer a.b.c")).getStatusCode());
    }

    @Test
    void jwtShapedTokenWithoutDecoderFallsBackToSessionLookup() {
        when(jwtProvider.getIfAvailable()).thenReturn(null);
        // No local session matches a JWT-shaped token, so it is rejected rather than trusted.
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> auth.require("Bearer a.b.c")).getStatusCode());
    }

    @Test
    void rbacRequireOneOfEnforcesRoles() {
        String token = loginToken("client", "CUSTOMER", null);
        assertEquals(Role.CUSTOMER, auth.requireOneOf("Bearer " + token, Role.CUSTOMER, Role.MANAGER).role());
        assertEquals(HttpStatus.FORBIDDEN, assertThrows(ResponseStatusException.class,
                () -> auth.requireOneOf("Bearer " + token, Role.MANAGER)).getStatusCode());
    }

    @Test
    void managerLoginRequiresAuthKey() {
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> loginToken("manager", "MANAGER", null)).getStatusCode());
        assertEquals(HttpStatus.UNAUTHORIZED, assertThrows(ResponseStatusException.class,
                () -> loginToken("manager", "MANAGER", "wrong-key")).getStatusCode());
        String token = loginToken("manager", "MANAGER", "manager-local-key");
        assertEquals(Role.MANAGER, auth.require("Bearer " + token).role());
    }
}