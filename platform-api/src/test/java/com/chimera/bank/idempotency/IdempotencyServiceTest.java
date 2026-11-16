package com.chimera.bank.idempotency;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class IdempotencyServiceTest {
    private IdempotencyKeyRepository repository;
    private SimpleMeterRegistry registry;
    private ObjectMapper mapper;
    private IdempotencyService service;

    @BeforeEach
    void setUp() {
        repository = mock(IdempotencyKeyRepository.class);
        registry = new SimpleMeterRegistry();
        mapper = new ObjectMapper();
        service = new IdempotencyService(repository, mapper, registry);
        when(repository.saveAndFlush(any())).thenAnswer(inv -> inv.getArgument(0));
        when(repository.save(any())).thenAnswer(inv -> inv.getArgument(0));
    }

    @Test
    void firstExecutionRunsActionAndCompletesKey() {
        when(repository.findById("k1")).thenReturn(Optional.empty());
        AtomicInteger calls = new AtomicInteger();
        IdempotencyService.Result<String> result = service.execute(
                "k1", "checkout.create", "body", String.class, () -> { calls.incrementAndGet(); return "created"; });
        assertFalse(result.replayed());
        assertEquals("created", result.value());
        assertEquals(1, calls.get());
        ArgumentCaptor<IdempotencyKeyEntity> captor = ArgumentCaptor.forClass(IdempotencyKeyEntity.class);
        verify(repository).save(captor.capture());
        assertEquals(IdempotencyKeyEntity.Status.COMPLETED, captor.getValue().getStatus());
    }

    @Test
    void completedKeyReplaysWithoutReRunningAction() throws Exception {
        IdempotencyKeyEntity stored = new IdempotencyKeyEntity();
        stored.setId("k1");
        stored.setRequestHash(hash("body"));
        stored.setStatus(IdempotencyKeyEntity.Status.COMPLETED);
        stored.setResponseJson(mapper.writeValueAsString("created"));
        when(repository.findById("k1")).thenReturn(Optional.of(stored));
        AtomicInteger calls = new AtomicInteger();
        IdempotencyService.Result<String> result = service.execute(
                "k1", "checkout.create", "body", String.class, () -> { calls.incrementAndGet(); return "again"; });
        assertTrue(result.replayed());
        assertEquals("created", result.value());
        assertEquals(0, calls.get());
        verify(repository, never()).saveAndFlush(any());
        assertEquals(1.0, registry.get("chimera_idempotency_duplicates_total").counter().count());
    }

    @Test
    void sameKeyDifferentBodyIsRejected() throws Exception {
        IdempotencyKeyEntity stored = new IdempotencyKeyEntity();
        stored.setId("k1");
        stored.setRequestHash(hash("body"));
        stored.setStatus(IdempotencyKeyEntity.Status.COMPLETED);
        stored.setResponseJson("\"created\"");
        when(repository.findById("k1")).thenReturn(Optional.of(stored));
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                service.execute("k1", "checkout.create", "different", String.class, () -> "x"));
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, ex.getStatusCode());
    }

    @Test
    void inProgressKeyConflicts() throws Exception {
        IdempotencyKeyEntity stored = new IdempotencyKeyEntity();
        stored.setId("k1");
        stored.setRequestHash(hash("body"));
        stored.setStatus(IdempotencyKeyEntity.Status.IN_PROGRESS);
        when(repository.findById("k1")).thenReturn(Optional.of(stored));
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                service.execute("k1", "checkout.create", "body", String.class, () -> "x"));
        assertEquals(HttpStatus.CONFLICT, ex.getStatusCode());
    }

    @Test
    void insertRaceConflicts() {
        when(repository.findById("k1")).thenReturn(Optional.empty());
        when(repository.saveAndFlush(any())).thenThrow(new DataIntegrityViolationException("duplicate pk"));
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                service.execute("k1", "checkout.create", "body", String.class, () -> "x"));
        assertEquals(HttpStatus.CONFLICT, ex.getStatusCode());
    }

    @Test
    void blankKeyIsRejected() {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                service.execute("  ", "checkout.create", "body", String.class, () -> "x"));
        assertEquals(HttpStatus.BAD_REQUEST, ex.getStatusCode());
    }

    private String hash(Object body) throws Exception {
        String json = mapper.writeValueAsString(body);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        return HexFormat.of().formatHex(digest.digest(json.getBytes(StandardCharsets.UTF_8)));
    }
}