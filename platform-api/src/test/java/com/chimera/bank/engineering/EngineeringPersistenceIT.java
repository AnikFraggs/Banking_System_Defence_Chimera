package com.chimera.bank.engineering;

import com.chimera.bank.idempotency.IdempotencyKeyEntity;
import com.chimera.bank.idempotency.IdempotencyKeyRepository;
import com.chimera.bank.idempotency.IdempotencyService;
import com.chimera.bank.outbox.OutboxEventEntity;
import com.chimera.bank.outbox.OutboxEventRepository;
import com.chimera.bank.saga.SagaInstanceEntity;
import com.chimera.bank.saga.SagaInstanceRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Integration test against a real PostgreSQL (Testcontainers). Verifies that the Flyway migration
 * creates the engineering tables and that idempotency / outbox / saga persistence works on real SQL,
 * not just mocks. Tagged {@code integration} so it runs only under {@code mvn verify -Pintegration}.
 */
@DataJpaTest(properties = {"spring.jpa.hibernate.ddl-auto=update", "spring.flyway.enabled=true"})
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
// Skip (not fail) when docker-java cannot reach a Docker daemon, e.g. some
// Windows Docker Desktop named-pipe setups. Runs in Linux CI where Docker works.
@Testcontainers(disabledWithoutDocker = true)
@Tag("integration")
class EngineeringPersistenceIT {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:15-alpine");

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
    }

    @Autowired IdempotencyKeyRepository idempotencyKeys;
    @Autowired OutboxEventRepository outboxEvents;
    @Autowired SagaInstanceRepository sagaInstances;
    @Autowired JdbcTemplate jdbc;

    @Test
    void flywayCreatesEngineeringTables() {
        List<String> tables = jdbc.queryForList(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'", String.class);
        assertTrue(tables.contains("idempotency_keys"), "Flyway must create idempotency_keys; got " + tables);
        assertTrue(tables.contains("outbox_events"), "Flyway must create outbox_events; got " + tables);
        assertTrue(tables.contains("saga_instances"), "Flyway must create saga_instances; got " + tables);
        assertTrue(tables.contains("flyway_schema_history"), "Flyway history table must exist");
    }

    @Test
    void idempotencyReplaysOnRealPostgres() {
        IdempotencyService service = new IdempotencyService(idempotencyKeys, new ObjectMapper(), new SimpleMeterRegistry());
        AtomicInteger calls = new AtomicInteger();
        IdempotencyService.Result<String> first = service.execute(
                "it-key-1", "checkout.create", "body", String.class, () -> { calls.incrementAndGet(); return "created"; });
        IdempotencyService.Result<String> second = service.execute(
                "it-key-1", "checkout.create", "body", String.class, () -> { calls.incrementAndGet(); return "again"; });
        assertFalse(first.replayed());
        assertTrue(second.replayed());
        assertEquals("created", second.value());
        assertEquals(1, calls.get(), "the action must run exactly once across a replay");
        assertEquals(IdempotencyKeyEntity.Status.COMPLETED, idempotencyKeys.findById("it-key-1").orElseThrow().getStatus());
    }

    @Test
    void outboxEventPersistsAndIsPollable() {
        OutboxEventEntity event = new OutboxEventEntity();
        event.setAggregateType("CheckoutOrder");
        event.setAggregateId(UUID.randomUUID());
        event.setEventType("ORDER_CAPTURED");
        event.setPayload("{\"amount\":\"25.00\"}");
        event.setStatus(OutboxEventEntity.Status.NEW);
        outboxEvents.saveAndFlush(event);
        List<OutboxEventEntity> polled = outboxEvents.findTop50ByStatusOrderByCreatedAtAsc(OutboxEventEntity.Status.NEW);
        assertTrue(polled.stream().anyMatch(e -> e.getId().equals(event.getId())));
    }

    @Test
    void sagaInstancePersists() {
        SagaInstanceEntity saga = new SagaInstanceEntity();
        saga.setOrderId(UUID.randomUUID());
        saga.setType("SETTLEMENT");
        saga.setStatus(SagaInstanceEntity.Status.RUNNING);
        saga.setCurrentStep("CAPTURE");
        sagaInstances.saveAndFlush(saga);
        SagaInstanceEntity loaded = sagaInstances.findById(saga.getId()).orElseThrow();
        assertEquals(SagaInstanceEntity.Status.RUNNING, loaded.getStatus());
        assertEquals("CAPTURE", loaded.getCurrentStep());
    }
}