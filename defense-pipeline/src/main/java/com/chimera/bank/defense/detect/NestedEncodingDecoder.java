package com.chimera.bank.defense.detect;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Recursively decodes base64 (and nested base64-within-base64) segments found in
 * a payload so the injection scanner can inspect what an attacker tried to hide
 * under one or more encoding layers.
 *
 * <p>Attack it defends against: {@code "please run "} + base64(base64("ignore all
 * previous instructions")). A single-pass scanner sees only opaque base64 and
 * passes it through; a downstream tool that decodes it then executes the hidden
 * instruction. This decoder peels every layer (bounded depth) and returns the
 * decoded strings so the scanner can pattern-match against them.
 *
 * <p>Detect-only: it decodes the bank's own inbound text to inspect it. It never
 * encodes payloads for any external target.
 */
public final class NestedEncodingDecoder {

    /** Bounded recursion so a malicious deeply-nested blob can't cause runaway work. */
    private static final int MAX_DEPTH = 4;
    private static final int MIN_SEGMENT_LEN = 12;   // ignore short tokens that decode to noise
    private static final int MAX_SEGMENTS_PER_LEVEL = 8;

    // Candidate base64 runs: base64url + standard alphabet, optional padding.
    private static final Pattern B64_SEGMENT =
            Pattern.compile("[A-Za-z0-9+/_-]{" + MIN_SEGMENT_LEN + ",}={0,2}");

    private NestedEncodingDecoder() {
    }

    public record DecodeResult(List<String> decodedLayers, int maxDepthReached) {
        /** All decoded text joined, for a single pattern-scan pass. */
        public String joined() {
            return String.join("\n", decodedLayers);
        }

        public boolean foundEncoding() {
            return !decodedLayers.isEmpty();
        }
    }

    public static DecodeResult decodeAll(String input) {
        List<String> layers = new ArrayList<>();
        int depth = peel(input, 0, layers);
        return new DecodeResult(List.copyOf(layers), depth);
    }

    private static int peel(String text, int depth, List<String> out) {
        if (text == null || text.isEmpty() || depth >= MAX_DEPTH) {
            return depth;
        }
        int maxDepth = depth;
        Matcher m = B64_SEGMENT.matcher(text);
        int segments = 0;
        while (m.find() && segments < MAX_SEGMENTS_PER_LEVEL) {
            String seg = m.group();
            String decoded = tryDecode(seg);
            if (decoded != null && isMostlyPrintable(decoded) && !decoded.equals(seg)) {
                segments++;
                out.add(decoded);
                // Recurse: the decoded text may itself contain another base64 layer.
                int d = peel(decoded, depth + 1, out);
                if (d > maxDepth) {
                    maxDepth = d;
                }
            }
        }
        return maxDepth;
    }

    private static String tryDecode(String seg) {
        // Try standard, then URL-safe. Length must be plausible for base64.
        String decoded = tryWith(Base64.getDecoder(), seg);
        if (decoded == null) {
            decoded = tryWith(Base64.getUrlDecoder(), normalizeUrl(seg));
        }
        return decoded;
    }

    private static String tryWith(Base64.Decoder decoder, String seg) {
        try {
            byte[] raw = decoder.decode(stripToDecodable(seg));
            if (raw.length == 0) {
                return null;
            }
            return new String(raw, StandardCharsets.UTF_8);
        } catch (IllegalArgumentException ignored) {
            return null;
        }
    }

    /** Base64 length must be a multiple of 4; trim the trailing partial group. */
    private static String stripToDecodable(String seg) {
        int usable = seg.length() - (seg.length() % 4);
        return usable <= 0 ? seg : seg.substring(0, usable);
    }

    private static String normalizeUrl(String seg) {
        return seg.replace('+', '-').replace('/', '_');
    }

    /** Guard against treating random bytes as text: require mostly printable output. */
    private static boolean isMostlyPrintable(String s) {
        if (s.isEmpty()) {
            return false;
        }
        int printable = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c >= 0x20 && c < 0x7F || c == '\n' || c == '\t' || c == '\r') {
                printable++;
            }
        }
        return (double) printable / s.length() >= 0.85;
    }
}
