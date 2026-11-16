package com.chimera.bank.auth;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.Optional;

public interface AuthSessionRepository extends JpaRepository<AuthSessionEntity, String> {
    Optional<AuthSessionEntity> findByTokenHashAndExpiresAtAfter(String tokenHash, Instant now);
    long deleteByExpiresAtBefore(Instant now);
}
