package com.chimera.bank.defense.metrics;

/**
 * Small, dependency-free statistics helpers for evaluating the defense pipeline:
 * Pearson correlation and RMSE between predicted and ground-truth severities.
 */
public final class Metrics {

    private Metrics() {
    }

    /** Pearson product-moment correlation coefficient r in [-1, 1]. */
    public static double pearson(double[] x, double[] y) {
        if (x.length != y.length || x.length == 0) {
            throw new IllegalArgumentException("arrays must be non-empty and equal length");
        }
        int n = x.length;
        double mx = mean(x);
        double my = mean(y);
        double sxy = 0, sxx = 0, syy = 0;
        for (int i = 0; i < n; i++) {
            double dx = x[i] - mx;
            double dy = y[i] - my;
            sxy += dx * dy;
            sxx += dx * dx;
            syy += dy * dy;
        }
        double denom = Math.sqrt(sxx * syy);
        return denom == 0 ? 0.0 : sxy / denom;
    }

    /** Root mean squared error between predicted and actual. */
    public static double rmse(double[] predicted, double[] actual) {
        if (predicted.length != actual.length || predicted.length == 0) {
            throw new IllegalArgumentException("arrays must be non-empty and equal length");
        }
        double sum = 0;
        for (int i = 0; i < predicted.length; i++) {
            double d = predicted[i] - actual[i];
            sum += d * d;
        }
        return Math.sqrt(sum / predicted.length);
    }

    public static double mean(double[] v) {
        double s = 0;
        for (double d : v) {
            s += d;
        }
        return s / v.length;
    }

    public static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    public static double precision(int truePos, int falsePos) {
        return truePos + falsePos == 0 ? 1.0 : (double) truePos / (truePos + falsePos);
    }

    public static double recall(int truePos, int falseNeg) {
        return truePos + falseNeg == 0 ? 1.0 : (double) truePos / (truePos + falseNeg);
    }

    public static double f1(double precision, double recall) {
        return precision + recall == 0 ? 0.0 : 2 * precision * recall / (precision + recall);
    }

    /**
     * Composite layer "health %" in [0,100]. A layer is healthy when it (a)
     * detects the malicious samples aimed at it (recall), (b) calibrates severity
     * well (low RMSE, high correlation), and (c) does not over-fire on benign
     * traffic (precision). We weight recall and calibration highest because a
     * missed attack is the worst outcome for a security ring.
     *
     * <p>{@code r} is clamped to [0,1] (negative correlation contributes nothing).
     */
    public static double healthPercent(double recall, double precision, double rmse, double r) {
        double calibration = (1.0 - Math.min(1.0, rmse)) * 0.5 + Math.max(0.0, Math.min(1.0, r)) * 0.5;
        double score = 0.45 * recall + 0.20 * precision + 0.35 * calibration;
        return Math.round(score * 1000.0) / 10.0;
    }
}
