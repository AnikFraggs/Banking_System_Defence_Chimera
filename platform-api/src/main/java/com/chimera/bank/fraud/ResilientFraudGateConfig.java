package com.chimera.bank.fraud;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import io.github.resilience4j.micrometer.tagged.TaggedCircuitBreakerMetrics;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import java.time.Duration;

/**
 * Wraps the configured fraud-gate transport in a circuit breaker. A fail-closed CHALLENGE fallback
 * counts as a failure, so a degraded gate trips the breaker and subsequent calls fast-fail to
 * CHALLENGE instead of waiting on the network. There are deliberately NO retries on this synchronous
 * path: retrying would multiply the per-call decision budget. Retries belong to the async outbox.
 */
@Configuration
public class ResilientFraudGateConfig {

    @Bean
    @Primary
    public FraudGateTransport resilientFraudGate(ObjectProvider<GrpcFraudGateClient> grpc,
                                                 ObjectProvider<FraudGateClient> http,
                                                 MeterRegistry registry) {
        FraudGateTransport resolved = grpc.getIfAvailable();
        if (resolved == null) resolved = http.getIfAvailable();
        if (resolved == null) {
            throw new IllegalStateException("No fraud-gate transport is configured");
        }
        final FraudGateTransport delegate = resolved;
        CircuitBreakerConfig config = CircuitBreakerConfig.custom()
                .failureRateThreshold(50f)
                .slidingWindowSize(20)
                .minimumNumberOfCalls(10)
                .waitDurationInOpenState(Duration.ofSeconds(10))
                .permittedNumberOfCallsInHalfOpenState(3)
                .recordResult(result -> result instanceof ScoreResponse response && gateDegraded(response))
                .build();
        CircuitBreakerRegistry breakerRegistry = CircuitBreakerRegistry.of(config);
        CircuitBreaker breaker = breakerRegistry.circuitBreaker("fraudGate");
        // Expose breaker state/call/failure-rate metrics to Prometheus (programmatic breakers
        // are not auto-bound by the Spring starter).
        TaggedCircuitBreakerMetrics.ofCircuitBreakerRegistry(breakerRegistry).bindTo(registry);
        return request -> {
            try {
                return breaker.executeSupplier(() -> delegate.score(request));
            } catch (CallNotPermittedException open) {
                return FraudGateFallback.challenge("GATE_CIRCUIT_OPEN",
                        "Fraud gate circuit is open; verification is required", 0.0);
            }
        };
    }

    // INVALID_FEATURES is a healthy gate (model loaded) rejecting one request's input, e.g. a manual
    // order without card features. Counting it let ordinary traffic open the breaker for every customer.
    static boolean gateDegraded(ScoreResponse response) {
        return response.fallback() && (response.reasons() == null
                || response.reasons().stream().noneMatch(reason -> "INVALID_FEATURES".equals(reason.code())));
    }
}