package com.chimera.bank.idempotency;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Optional;
import java.util.function.Supplier;

/**
 * Duplicate-request prevention backed by a unique primary key. A completed key replays the
 * stored response; the same key with a different body is rejected; an in-flight key conflicts.
 * The record commits in the same transaction as the business write, so a failed action leaves
 * no key behind and the client may safely retry.
 */
@Service
public class IdempotencyService {
    public record Result<T>(T value, boolean replayed) {}

    private final IdempotencyKeyRepository repository;
    private final ObjectMapper objectMapper;
    private final Counter duplicates;

    public IdempotencyService(IdempotencyKeyRepository repository, ObjectMapper objectMapper, MeterRegistry registry) {
        this.repository = repository;
        this.objectMapper = objectMapper;
        this.duplicates = Counter.builder("chimera_idempotency_duplicates_total")
                .description("Idempotent requests served from a stored response instead of re-executing")
                .register(registry);
    }

    @Transactional(propagation = Propagation.REQUIRED)
    public <T> Result<T> execute(String key, String scope, Object requestBody, Class<T> type, Supplier<T> action) {
        if (key == null || key.isBlank() || key.length() > 128) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key must be 1-128 characters");
        }
        String requestHash = sha256(writeJson(requestBody));
        Optional<IdempotencyKeyEntity> existing = repository.findById(key);
        if (existing.isPresent()) {
            IdempotencyKeyEntity record = existing.get();
            if (!record.getRequestHash().equals(requestHash)) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        "Idempotency-Key was already used with a different request body");
            }
            if (record.getStatus() == IdempotencyKeyEntity.Status.COMPLETED) {
                duplicates.increment();
                return new Result<>(readJson(record.getResponseJson(), type), true);
            }
            throw new ResponseStatusException(HttpStatus.CONFLICT, "A request with this Idempotency-Key is in progress");
        }

        IdempotencyKeyEntity record = new IdempotencyKeyEntity();
        record.setId(key);
        record.setScope(scope);
        record.setRequestHash(requestHash);
        record.setStatus(IdempotencyKeyEntity.Status.IN_PROGRESS);
        try {
            repository.saveAndFlush(record);
        } catch (DataIntegrityViolationException race) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "A request with this Idempotency-Key is in progress");
        }

        T value = action.get();
        record.setStatus(IdempotencyKeyEntity.Status.COMPLETED);
        record.setResponseJson(writeJson(value));
        repository.save(record);
        return new Result<>(value, false);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("Could not serialize idempotency payload", e);
        }
    }

    private <T> T readJson(String json, Class<T> type) {
        try {
            return objectMapper.readValue(json, type);
        } catch (Exception e) {
            throw new IllegalStateException("Could not replay idempotency response", e);
        }
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }
}