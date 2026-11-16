package com.chimera.bank.fraud;

import com.chimera.bank.fraud.grpc.FraudGateGrpc;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/** Persistent HTTP/2 gRPC transport. It deliberately never falls back to HTTP. */
@Component
@ConditionalOnProperty(prefix = "chimera.checkout.fraud-gate", name = "transport",
        havingValue = "grpc", matchIfMissing = true)
public final class GrpcFraudGateClient implements FraudGateTransport {
    private final ManagedChannel channel;
    private final FraudGateGrpc.FraudGateBlockingStub stub;
    private final long timeoutMs;

    @Autowired
    public GrpcFraudGateClient(
            @Value("${chimera.checkout.fraud-gate.grpc-target:localhost:50051}") String target,
            @Value("${chimera.checkout.fraud-gate.timeout-ms:300}") long timeoutMs,
            @Value("${chimera.checkout.fraud-gate.grpc-use-tls:false}") boolean useTls) {
        this(channel(target, useTls), timeoutMs);
    }

    GrpcFraudGateClient(ManagedChannel channel, long timeoutMs) {
        if (timeoutMs < 1) throw new IllegalArgumentException("Fraud-gate deadline must be positive");
        this.channel = channel;
        this.timeoutMs = timeoutMs;
        this.stub = FraudGateGrpc.newBlockingStub(channel);
    }

    private static ManagedChannel channel(String target, boolean useTls) {
        ManagedChannelBuilder<?> builder = ManagedChannelBuilder.forTarget(target);
        if (useTls) builder.useTransportSecurity();
        else builder.usePlaintext();
        return builder.build();
    }

    @Override
    public ScoreResponse score(ScoreRequest request) {
        long started = System.nanoTime();
        try {
            com.chimera.bank.fraud.grpc.ScoreResponse response = stub
                    .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
                    .scorePreCapture(FraudGateGrpcCodec.toProto(request));
            ScoreResponse scored = FraudGateGrpcCodec.fromProto(response);
            if (!scored.valid()) {
                return FraudGateFallback.challenge("GATE_ERROR",
                        "Fraud gate returned an invalid gRPC decision", elapsed(started));
            }
            return scored;
        } catch (StatusRuntimeException e) {
            if (e.getStatus().getCode() == Status.Code.DEADLINE_EXCEEDED) {
                return FraudGateFallback.challenge("GATE_TIMEOUT",
                        "Fraud gate exceeded its gRPC decision budget", elapsed(started));
            }
            return FraudGateFallback.challenge("GATE_ERROR",
                    "Fraud gate gRPC is unavailable; verification is required", elapsed(started));
        } catch (RuntimeException e) {
            return FraudGateFallback.challenge("GATE_ERROR",
                    "Fraud gate gRPC request could not be encoded; verification is required", elapsed(started));
        }
    }

    private double elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000.0;
    }

    @PreDestroy
    public void close() {
        channel.shutdown();
        try {
            if (!channel.awaitTermination(5, TimeUnit.SECONDS)) channel.shutdownNow();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            channel.shutdownNow();
        }
    }
}
