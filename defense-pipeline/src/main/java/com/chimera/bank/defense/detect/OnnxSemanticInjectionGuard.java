package com.chimera.bank.defense.detect;

import ai.onnxruntime.OnnxModelMetadata;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * Cached, in-process ONNX binary classifier. No model is downloaded by the
 * application. Both artifact paths are required to leave deterministic mode.
 */
@Component
public final class OnnxSemanticInjectionGuard implements SemanticInjectionGuard {
    private static final long MAX_MODEL_BYTES = 100_000_000L;

    private final long timeoutMs;
    private final double threshold;
    private final SemanticVerdictCache cache;
    private final ExecutorService executor;
    private OrtEnvironment environment;
    private OrtSession session;
    private WordPieceTokenizer tokenizer;
    private volatile Status status;

    @Autowired
    public OnnxSemanticInjectionGuard(
            @Value("${chimera.defense.l4.semantic.model-path:}") String modelPath,
            @Value("${chimera.defense.l4.semantic.vocab-path:}") String vocabPath,
            @Value("${chimera.defense.l4.semantic.max-sequence-length:128}") int maxSequenceLength,
            @Value("${chimera.defense.l4.semantic.max-input-chars:8192}") int maxInputChars,
            @Value("${chimera.defense.l4.semantic.timeout-ms:250}") long timeoutMs,
            @Value("${chimera.defense.l4.semantic.threshold:0.65}") double threshold,
            @Value("${chimera.defense.l4.semantic.cache-size:4096}") int cacheSize) {
        this.timeoutMs = timeoutMs;
        this.threshold = threshold;
        this.cache = new SemanticVerdictCache(cacheSize);
        this.executor = Executors.newSingleThreadExecutor(runnable -> {
            Thread thread = new Thread(runnable, "l4-semantic-onnx");
            thread.setDaemon(true);
            return thread;
        });

        boolean hasModel = modelPath != null && !modelPath.isBlank();
        boolean hasVocab = vocabPath != null && !vocabPath.isBlank();
        if (!hasModel && !hasVocab) {
            status = new Status(false, false,
                    "disabled: semantic model-path and vocab-path are not configured", ModelMetadata.empty());
            return;
        }
        if (!hasModel || !hasVocab) {
            status = new Status(true, false,
                    "unavailable: both semantic model-path and vocab-path must be configured", ModelMetadata.empty());
            return;
        }
        try {
            if (timeoutMs < 1 || timeoutMs > 1_000) {
                throw new IllegalArgumentException("Semantic timeout must be between 1 and 1000 ms");
            }
            if (!Double.isFinite(threshold) || threshold < 0 || threshold > 1) {
                throw new IllegalArgumentException("Semantic threshold must be in [0,1]");
            }
            Path model = Path.of(modelPath).toAbsolutePath().normalize();
            Path vocab = Path.of(vocabPath).toAbsolutePath().normalize();
            if (!Files.isRegularFile(model) || Files.size(model) >= MAX_MODEL_BYTES) {
                throw new IllegalArgumentException("Semantic ONNX model must be a regular file smaller than 100 MB");
            }
            if (!Files.isRegularFile(vocab) || Files.size(vocab) > 10_000_000L) {
                throw new IllegalArgumentException("Semantic vocabulary must be a regular file no larger than 10 MB");
            }
            tokenizer = new WordPieceTokenizer(vocab, maxSequenceLength, maxInputChars);
            environment = OrtEnvironment.getEnvironment();
            try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
                options.setIntraOpNumThreads(1);
                options.setInterOpNumThreads(1);
                session = environment.createSession(model.toString(), options);
            }
            status = new Status(true, true, "enabled: cached quantized ONNX semantic guard",
                    readMetadata(session.getMetadata()));
        } catch (Exception e) {
            closeNativeResources();
            status = new Status(true, false,
                    "unavailable: " + e.getClass().getSimpleName() + ": " + e.getMessage()
                            + "; requests fail safe to CHALLENGE",
                    ModelMetadata.empty());
        }
    }

    public OnnxSemanticInjectionGuard(String modelPath, String vocabPath, int maxSequenceLength,
                                      int maxInputChars, long timeoutMs, double threshold) {
        this(modelPath, vocabPath, maxSequenceLength, maxInputChars, timeoutMs, threshold, 4096);
    }

    /** Offline/test constructor with the same single-load behavior as Spring. */
    public OnnxSemanticInjectionGuard(String modelPath, String vocabPath) {
        this(modelPath, vocabPath, 128, 8192, 250, 0.65, 4096);
    }

    @Override
    public Result assess(String text) {
        Status current = status;
        if (!current.configured()) return new Result(false, 0.0, "semantic_guard_disabled");
        if (!current.available()) return new Result(true, 1.0, "semantic_guard_unavailable");
        if (text == null || text.isBlank()) return new Result(false, 0.0, "semantic_clear");

        String key = SemanticVerdictCache.key(text);
        var cached = cache.get(key);
        if (cached.isPresent()) return cached.get();

        Future<Result> future = executor.submit(new Inference(text));
        try {
            Result result = future.get(timeoutMs, TimeUnit.MILLISECONDS);
            cache.put(key, result);
            return result;
        } catch (TimeoutException e) {
            future.cancel(true);
            return new Result(true, 1.0, "semantic_guard_timeout");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            future.cancel(true);
            return new Result(true, 1.0, "semantic_guard_interrupted");
        } catch (ExecutionException | RuntimeException e) {
            future.cancel(true);
            return new Result(true, 1.0, "semantic_guard_inference_error");
        }
    }

    @Override
    public Status status() {
        return status;
    }

    public SemanticVerdictCache.Stats cacheStats() {
        return cache.stats();
    }

    private final class Inference implements Callable<Result> {
        private final String text;

        private Inference(String text) {
            this.text = text;
        }

        @Override
        public Result call() {
            Map<String, OnnxTensor> inputs = new HashMap<>();
            try {
                WordPieceTokenizer.Tokenized tokens = tokenizer.tokenize(text);
                for (String inputName : session.getInputNames()) {
                    OnnxTensor tensor = switch (inputName) {
                        case "input_ids" -> OnnxTensor.createTensor(environment, new long[][] {tokens.inputIds()});
                        case "attention_mask" -> OnnxTensor.createTensor(environment, new long[][] {tokens.attentionMask()});
                        case "token_type_ids" -> OnnxTensor.createTensor(environment, new long[][] {tokens.tokenTypeIds()});
                        default -> throw new IllegalArgumentException("Unsupported semantic model input: " + inputName);
                    };
                    inputs.put(inputName, tensor);
                }
                try (OrtSession.Result output = session.run(inputs)) {
                    if (output.size() != 1 || !(output.get(0) instanceof OnnxTensor tensor)) {
                        throw new IllegalArgumentException("Semantic model must return one binary logits tensor");
                    }
                    Object value = tensor.getValue();
                    if (!(value instanceof float[][] logits) || logits.length != 1 || logits[0].length != 2) {
                        throw new IllegalArgumentException("Semantic model output must have shape [1,2]");
                    }
                    float positive = logits[0][1];
                    float negative = logits[0][0];
                    if (!Float.isFinite(positive) || !Float.isFinite(negative)) {
                        throw new IllegalArgumentException("Semantic model returned non-finite logits");
                    }
                    double maximum = Math.max(positive, negative);
                    double positiveExp = Math.exp(positive - maximum);
                    double probability = positiveExp / (positiveExp + Math.exp(negative - maximum));
                    return probability >= threshold
                            ? new Result(true, probability, "semantic_prompt_injection")
                            : new Result(false, probability, "semantic_clear");
                }
            } catch (Exception e) {
                throw new IllegalStateException("ONNX semantic inference failed", e);
            } finally {
                inputs.values().forEach(OnnxTensor::close);
            }
        }
    }

    private static ModelMetadata readMetadata(OnnxModelMetadata metadata) {
        if (metadata == null) return ModelMetadata.empty();
        return new ModelMetadata(metadata.getDescription(), metadata.getDomain(), metadata.getGraphName(),
                metadata.getProducerName(), metadata.getVersion(), Map.copyOf(metadata.getCustomMetadata()));
    }

    @PreDestroy
    @Override
    public void close() {
        closeNativeResources();
        executor.shutdownNow();
    }

    private synchronized void closeNativeResources() {
        if (session != null) {
            try {
                session.close();
            } catch (Exception ignored) {
                // Shutdown is best effort after inference has stopped.
            }
            session = null;
        }
        if (environment != null) {
            try {
                environment.close();
            } catch (Exception ignored) {
                // The shared ORT environment may already be closed.
            }
            environment = null;
        }
    }
}
