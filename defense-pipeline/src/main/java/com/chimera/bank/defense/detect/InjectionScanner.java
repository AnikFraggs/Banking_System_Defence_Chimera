package com.chimera.bank.defense.detect;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Defensive scanner for text that will be shown to, or processed by, an LLM
 * layer. It detects:
 *
 * <ul>
 *   <li><b>Invisible-Unicode / zero-width steganography</b> — zero-width
 *       joiners/non-joiners, zero-width space, BOM, and Unicode tag characters
 *       (U+E0000..U+E007F) that can smuggle hidden instructions past a human
 *       reviewer but are still read by a model.</li>
 *   <li><b>Prompt-injection phrasing</b> — common override/exfiltration
 *       patterns ("ignore previous instructions", "reveal system prompt", ...).</li>
 *   <li><b>Bidi control characters</b> — used in "Trojan Source" style attacks.</li>
 *   <li><b>Homoglyph / confusable evasion</b> — mixed-script lookalikes
 *       ({@code іgnоrе}) that dodge a literal pattern match; folded to an ASCII
 *       skeleton via {@link ConfusableNormalizer} before scanning.</li>
 *   <li><b>Nested base64 encoding</b> — override phrases hidden under one or more
 *       base64 layers; peeled by {@link NestedEncodingDecoder} and re-scanned.</li>
 * </ul>
 *
 * This class only <em>detects and sanitizes</em>. It never constructs payloads.
 */
public final class InjectionScanner {

    // Zero-width and invisible formatting characters commonly abused for stego.
    private static final int[] ZERO_WIDTH = {
            0x200B, // ZERO WIDTH SPACE
            0x200C, // ZERO WIDTH NON-JOINER
            0x200D, // ZERO WIDTH JOINER
            0x2060, // WORD JOINER
            0xFEFF, // ZERO WIDTH NO-BREAK SPACE / BOM
            0x00AD  // SOFT HYPHEN
    };

    // Unicode bidirectional controls (Trojan Source).
    private static final int[] BIDI = {
            0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069
    };

    private static final List<Pattern> INJECTION_PATTERNS = List.of(
            Pattern.compile("(?i)ignore\\s+(all\\s+)?(previous|prior|above)\\s+instructions"),
            Pattern.compile("(?i)disregard\\s+(the\\s+)?(system|earlier)\\s+prompt"),
            Pattern.compile("(?i)reveal|print|show\\s+(your\\s+)?(system|hidden)\\s+prompt"),
            Pattern.compile("(?i)you\\s+are\\s+now\\s+(a|an|in)\\s+"),
            Pattern.compile("(?i)exfiltrate|leak|send\\s+.*(secret|key|token|credential)"),
            Pattern.compile("(?i)base64|eval\\(|exec\\(|<script")
    );

    public record ScanReport(
            boolean invisibleChars,
            int invisibleCount,
            boolean bidiControls,
            boolean injectionPhrasing,
            boolean homoglyphEvasion,
            boolean nestedEncoding,
            int encodingDepth,
            List<String> matchedPatterns,
            String sanitized) {

        public boolean clean() {
            return !invisibleChars && !bidiControls && !injectionPhrasing
                    && !homoglyphEvasion && !nestedEncoding;
        }

        public double severity() {
            double s = 0.0;
            if (invisibleChars) s += 0.4 + Math.min(0.3, invisibleCount * 0.02);
            if (bidiControls) s += 0.3;
            if (injectionPhrasing) s += 0.5;
            // A phrase disguised with homoglyphs OR buried under encoding layers is
            // deliberate evasion — weight it at least as high as plain injection.
            if (homoglyphEvasion) s += 0.45;
            if (nestedEncoding) s += 0.3 + Math.min(0.3, Math.max(0, encodingDepth - 1) * 0.15);
            return Math.min(1.0, s);
        }
    }

    public ScanReport scan(String input) {
        String text = input == null ? "" : input;
        int invisible = 0;
        boolean bidi = false;
        StringBuilder sanitized = new StringBuilder(text.length());

        for (int i = 0; i < text.length(); ) {
            int cp = text.codePointAt(i);
            i += Character.charCount(cp);
            if (isZeroWidth(cp)) {
                invisible++;
                continue; // strip
            }
            if (isBidi(cp)) {
                bidi = true;
                continue; // strip
            }
            // Unicode tag block used to smuggle instructions (U+E0000..U+E007F).
            if (cp >= 0xE0000 && cp <= 0xE007F) {
                invisible++;
                continue;
            }
            sanitized.appendCodePoint(cp);
        }

        // Fold homoglyphs to an ASCII skeleton and peel nested base64, so injection
        // patterns are matched against the raw text, the de-disguised skeleton, and
        // anything hidden under encoding layers.
        String folded = ConfusableNormalizer.fold(text);
        boolean homoglyph = ConfusableNormalizer.containsConfusables(text);
        NestedEncodingDecoder.DecodeResult decoded = NestedEncodingDecoder.decodeAll(text);

        List<String> matched = new ArrayList<>();
        boolean homoglyphEvasion = false;
        boolean nestedEncoding = false;
        for (Pattern p : INJECTION_PATTERNS) {
            if (p.matcher(text).find()) {
                matched.add(p.pattern());
            } else if (homoglyph && p.matcher(folded).find()) {
                matched.add(p.pattern() + " [homoglyph]");
                homoglyphEvasion = true;
            } else if (decoded.foundEncoding() && p.matcher(decoded.joined()).find()) {
                matched.add(p.pattern() + " [nested-b64]");
                nestedEncoding = true;
            }
        }

        return new ScanReport(
                invisible > 0, invisible, bidi, !matched.isEmpty(),
                homoglyphEvasion, nestedEncoding, decoded.maxDepthReached(),
                matched, sanitized.toString());
    }

    private static boolean isZeroWidth(int cp) {
        for (int z : ZERO_WIDTH) {
            if (cp == z) return true;
        }
        return false;
    }

    private static boolean isBidi(int cp) {
        for (int b : BIDI) {
            if (cp == b) return true;
        }
        return false;
    }
}
