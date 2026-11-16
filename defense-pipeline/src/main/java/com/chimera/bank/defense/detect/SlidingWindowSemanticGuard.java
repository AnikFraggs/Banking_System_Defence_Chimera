package com.chimera.bank.defense.detect;

import java.util.Objects;

/**
 * Sliding-window decorator that fixes the L4 long-payload blind spot.
 *
 * <p>The base {@link OnnxSemanticInjectionGuard} head-truncates to {@code maxSequenceLength}
 * (128 tokens) and {@code maxInputChars}. Measured v4 misses: 54.3% of false negatives sit
 * past token 126, so a single head-only pass structurally cannot see late-payload injections.
 * This decorator scans overlapping windows across the WHOLE text and max-pools the scores.
 *
 * <p>Safety properties (all preserved):
 * <ul>
 *   <li><b>Escalate-only:</b> the returned score is the max over windows, which always
 *       includes the head window, so it is never lower than a head-only pass. It can only
 *       raise risk, never lower it.</li>
 *   <li><b>Fail-closed:</b> the delegate already returns {@code Result(true, 1.0, ...)} on
 *       unavailable/timeout/error; max-pooling propagates that. If the window budget or the
 *       global deadline is exhausted while text remains uninspected, this returns a CHALLENGE
 *       rather than silently passing the unseen tail.</li>
 *   <li><b>Bounded latency:</b> a global deadline (default 220ms, under the 250ms L4 budget)
 *       plus early-exit on the first challenging window keep the common case fast. Malicious
 *       text usually trips an early window; only long BENIGN text scans every window, and is
 *       stepped up (not blocked) if it cannot be fully covered in budget.</li>
 * </ul>
 *
 * <p>Wiring: decorate the existing guard bean, e.g.
 * {@code @Bean @Primary SemanticInjectionGuard slidingWindow(OnnxSemanticInjectionGuard base)
 * { return SlidingWindowSemanticGuard.wrap(base); }}. This class adds no Spring annotations so
 * it cannot conflict with the existing component scan. Tune windowChars/strideChars/maxWindows/
 * globalDeadlineMs against measured per-window CPU inference on the target host.
 */
public final class SlidingWindowSemanticGuard implements SemanticInjectionGuard {

    private final SemanticInjectionGuard delegate;
    private final int windowChars;
    private final int strideChars;
    private final int maxWindows;
    private final long globalDeadlineMs;

    public SlidingWindowSemanticGuard(SemanticInjectionGuard delegate, int windowChars,
                                      int strideChars, int maxWindows, long globalDeadlineMs) {
        this.delegate = Objects.requireNonNull(delegate, "delegate");
        if (windowChars < 1) {
            throw new IllegalArgumentException("windowChars must be >= 1");
        }
        if (strideChars < 1 || strideChars > windowChars) {
            throw new IllegalArgumentException("strideChars must be in [1, windowChars]");
        }
        if (maxWindows < 1) {
            throw new IllegalArgumentException("maxWindows must be >= 1");
        }
        if (globalDeadlineMs < 1) {
            throw new IllegalArgumentException("globalDeadlineMs must be >= 1");
        }
        this.windowChars = windowChars;
        this.strideChars = strideChars;
        this.maxWindows = maxWindows;
        this.globalDeadlineMs = globalDeadlineMs;
    }

    /** Defaults: ~128-token windows, 200-char overlap, 12 windows, 220ms global deadline. */
    public static SlidingWindowSemanticGuard wrap(SemanticInjectionGuard delegate) {
        return new SlidingWindowSemanticGuard(delegate, 600, 400, 12, 220);
    }

    @Override
    public Result assess(String text) {
        Status status = delegate.status();
        if (!status.configured()) {
            // Guard disabled: preserve the deterministic baseline's pass-through behavior.
            return delegate.assess(text);
        }
        if (text == null || text.isEmpty()) {
            return Result.pass();
        }
        int length = text.length();
        if (length <= windowChars) {
            // Short prompt: a single head pass already covers it; no windowing overhead.
            return delegate.assess(text);
        }

        long deadlineNanos = System.nanoTime() + globalDeadlineMs * 1_000_000L;
        double maxScore = 0.0;
        String maxReason = "semantic_window_clear";
        int windows = 0;
        int start = 0;
        while (start < length) {
            if (windows >= maxWindows) {
                return new Result(true, Math.max(maxScore, 1.0),
                        "semantic_window_budget_exceeded: tail uninspected after " + windows + " windows");
            }
            if (System.nanoTime() >= deadlineNanos) {
                return new Result(true, Math.max(maxScore, 1.0),
                        "semantic_window_deadline_exceeded: tail uninspected after " + windows + " windows");
            }
            int end = Math.min(length, start + windowChars);
            Result result = delegate.assess(text.substring(start, end));
            windows++;
            if (result.score() > maxScore) {
                maxScore = result.score();
                maxReason = result.reason();
            }
            if (result.challenge()) {
                // Escalate-only decision reached; no need to inspect further windows.
                return new Result(true, Math.max(maxScore, result.score()),
                        "semantic_window_challenge@char" + start + ": " + result.reason());
            }
            if (end == length) {
                break; // tail fully covered
            }
            start += strideChars;
        }
        return new Result(false, maxScore, maxReason);
    }

    @Override
    public Status status() {
        Status base = delegate.status();
        String detail = base.detail() + " [sliding-window windowChars=" + windowChars
                + " strideChars=" + strideChars + " maxWindows=" + maxWindows
                + " globalDeadlineMs=" + globalDeadlineMs + "]";
        return new Status(base.configured(), base.available(), detail, base.metadata());
    }

    @Override
    public void close() {
        delegate.close();
    }
}