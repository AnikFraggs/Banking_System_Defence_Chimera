package com.chimera.bank.defense.detect;

import java.util.Map;

/**
 * Optional semantic prompt-injection detector. Implementations must be bounded
 * and fail safe; deterministic L4 checks still run after this detector.
 */
public interface SemanticInjectionGuard extends AutoCloseable {
    record Result(boolean challenge, double score, String reason) {
        public static Result pass() {
            return new Result(false, 0.0, "semantic_guard_disabled_or_clear");
        }
    }

    record ModelMetadata(String description, String domain, String graphName,
                         String producerName, long version, Map<String, String> custom) {
        public static ModelMetadata empty() {
            return new ModelMetadata("", "", "", "", 0, Map.of());
        }
    }

    record Status(boolean configured, boolean available, String detail, ModelMetadata metadata) {}

    Result assess(String text);

    Status status();

    static SemanticInjectionGuard disabled() {
        return new SemanticInjectionGuard() {
            private final Status status = new Status(false, false,
                    "disabled: set both semantic model and vocab paths to enable", ModelMetadata.empty());

            @Override
            public Result assess(String text) {
                return new Result(false, 0.0, "semantic_guard_disabled");
            }

            @Override
            public Status status() {
                return status;
            }

            @Override
            public void close() {
                // No resources in the deterministic baseline.
            }
        };
    }

    @Override
    default void close() {
        // Optional resources.
    }
}
