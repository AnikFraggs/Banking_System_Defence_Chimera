package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Local-only identity service backed by PostgreSQL.
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

    private final Map<String, Principal> sessions = new ConcurrentHashMap<>();
    private final byte[] managerAuthKey;
    private final UserRepository userRepository;
    private final AuthSessionRepository authSessionRepository;
    private final org.springframework.beans.factory.ObjectProvider<JwtTokenService> jwtTokenService;
    private final PasswordEncoder passwordEncoder;

    @Autowired
    public AuthService(@Value("${chimera.auth.manager.key:manager-local-key}") String managerAuthKey,
                       UserRepository userRepository, AuthSessionRepository authSessionRepository,
                       org.springframework.beans.factory.ObjectProvider<JwtTokenService> jwtTokenService) {
        this.managerAuthKey = (managerAuthKey == null ? "" : managerAuthKey).getBytes(StandardCharsets.UTF_8);
        this.userRepository = userRepository;
        this.authSessionRepository = authSessionRepository;
        this.jwtTokenService = jwtTokenService;
        this.passwordEncoder = new BCryptPasswordEncoder();

        // Seed the default demo users into the database if they don't exist yet
        seedDefaultUsers();
        migrateLegacyPlaintextPasswords();
    }

    /** Test/local compatibility constructor; production uses the persistent repository constructor. */
    AuthService(String managerAuthKey, UserRepository userRepository,
                org.springframework.beans.factory.ObjectProvider<JwtTokenService> jwtTokenService) {
        this.managerAuthKey = (managerAuthKey == null ? "" : managerAuthKey).getBytes(StandardCharsets.UTF_8);
        this.userRepository = userRepository;
        this.authSessionRepository = null;
        this.jwtTokenService = jwtTokenService;
        this.passwordEncoder = new BCryptPasswordEncoder();
    }

    /**
     * One-time upgrade path: earlier builds stored passwords in plaintext. Any
     * stored credential that is not already a BCrypt hash is re-hashed in place so
     * existing accounts keep working after the switch to {@link PasswordEncoder}.
     */
    private void migrateLegacyPlaintextPasswords() {
        for (AppUser user : userRepository.findAll()) {
            String stored = user.getPassword();
            if (stored != null && !stored.startsWith("$2a$") && !stored.startsWith("$2b$") && !stored.startsWith("$2y$")) {
                user.setPassword(passwordEncoder.encode(stored));
                userRepository.save(user);
            }
        }
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    private void seedDefaultUsers() {
        if (userRepository.findByUsername("client").isEmpty()) {
            AppUser client = new AppUser();
            client.setUsername("client");
            client.setPassword(passwordEncoder.encode("demo-pass"));
            client.setRole(Role.CUSTOMER.name());
            client.setRegistrationNumber("CUST-1001");
            client.setAccountNumber("CHM-1024-1189");
            client.setCustomerName("Anita Rao");
            client.setBalance(256400.00);
            userRepository.save(client);
        }
        if (userRepository.findByUsername("accountant").isEmpty()) {
            AppUser accountant = new AppUser();
            accountant.setUsername("accountant");
            accountant.setPassword(passwordEncoder.encode("demo-pass"));
            accountant.setRole(Role.ACCOUNTANT.name());
            accountant.setRegistrationNumber("ACC-001");
            accountant.setAccountNumber("CHM-ACC-001");
            accountant.setCustomerName("Dev Mehta");
            accountant.setBalance(0.0);
            userRepository.save(accountant);
        }
        if (userRepository.findByUsername("manager").isEmpty()) {
            AppUser manager = new AppUser();
            manager.setUsername("manager");
            manager.setPassword(passwordEncoder.encode("demo-pass"));
            manager.setRole(Role.MANAGER.name());
            manager.setRegistrationNumber("MGR-ROOT");
            manager.setAccountNumber("CHM-MGR-001");
            manager.setCustomerName("Maya Sen");
            manager.setBalance(0.0);
            userRepository.save(manager);
        }
    }

    public SessionView login(LoginRequest request) {
        if (request == null || request.username() == null || request.password() == null || request.role() == null) {
            throw unauthorized("Username, password, and role are required.");
        }
        
        // 1. Fetch user from PostgreSQL Database
        AppUser user = userRepository.findByUsername(request.username().trim().toLowerCase())
                .orElseThrow(() -> unauthorized("Invalid credentials or role."));
                
        Role requestedRole = parseRole(request.role());
        
        // 2. Verify password and role
        if (!passwordEncoder.matches(request.password(), user.getPassword()) || !Role.valueOf(user.getRole()).equals(requestedRole)) {
            throw unauthorized("Invalid credentials or role.");
        }
        
        // 3. Manager Auth Key Check
        if (requestedRole == Role.MANAGER && !managerKeyMatches(request.authKey())) {
            throw unauthorized("A valid manager authorization key is required.");
        }
        
        // 4. Create Session
        Instant expiresAt = Instant.now().plusSeconds(8 * 60 * 60);
        // Note: We map user.getUsername() to registrationNumber in the Principal so BankService can fetch by username
        Principal principal = new Principal(user.getUsername(), user.getCustomerName(), requestedRole, expiresAt);
        String token = UUID.randomUUID().toString();
        sessions.put(token, principal);
        if (authSessionRepository != null) {
            AuthSessionEntity session = new AuthSessionEntity();
            session.setTokenHash(tokenHash(token));
            session.setUsername(principal.registrationNumber());
            session.setDisplayName(principal.displayName());
            session.setRole(principal.role().name());
            session.setExpiresAt(expiresAt);
            authSessionRepository.save(session);
        }
        
        return new SessionView(token, principal.registrationNumber(), principal.displayName(),
                principal.role().name(), expiresAt);
    }

    public Principal require(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw unauthorized("Sign in is required.");
        }
        String token = authorization.substring("Bearer ".length()).trim();
        // A JWT (three dot-separated segments) is validated through the OIDC decoder when enabled.
        if (token.chars().filter(c -> c == '.').count() == 2) {
            JwtTokenService jwt = jwtTokenService.getIfAvailable();
            if (jwt != null) {
                return jwt.authenticate(token)
                        .orElseThrow(() -> unauthorized("The presented JWT is invalid or expired."));
            }
        }
        Principal principal = authSessionRepository == null ? sessions.get(token)
                : authSessionRepository.findByTokenHashAndExpiresAtAfter(tokenHash(token), Instant.now())
                    .map(session -> new Principal(session.getUsername(), session.getDisplayName(),
                            parseRole(session.getRole()), session.getExpiresAt()))
                    .orElse(null);
        if (principal == null || principal.expiresAt().isBefore(Instant.now())) {
            sessions.remove(token);
            throw unauthorized("Your local session has expired. Please sign in again.");
        }
        return principal;
    }

    /**
     * Non-throwing token resolution for the security filter chain. Returns the
     * principal when the bearer token is valid, otherwise empty so the request
     * stays anonymous and {@code @PreAuthorize} / the service layer can deny it.
     */
    public Optional<Principal> resolve(String authorization) {
        try {
            return Optional.of(require(authorization));
        } catch (ResponseStatusException ex) {
            return Optional.empty();
        }
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

    /** Invalidate the session associated with the bearer token (logout). */
    public void logout(String authorization) {
        if (authorization != null && authorization.startsWith("Bearer ")) {
            String token = authorization.substring("Bearer ".length()).trim();
            sessions.remove(token);
            if (authSessionRepository != null) authSessionRepository.deleteById(tokenHash(token));
        }
    }

    private static String tokenHash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    @Scheduled(fixedDelayString = "${chimera.auth.session.cleanup-ms:3600000}")
    public void removeExpiredSessions() {
        if (authSessionRepository != null) authSessionRepository.deleteByExpiresAtBefore(Instant.now());
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
