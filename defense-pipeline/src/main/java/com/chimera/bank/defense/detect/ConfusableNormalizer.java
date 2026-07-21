package com.chimera.bank.defense.detect;

import java.util.Map;

/**
 * Folds Unicode "confusables" (homoglyphs) back to their ASCII skeleton so that
 * an attacker cannot slip a payload past the pattern scanner by spelling
 * {@code "іgnоrе"} with Cyrillic <em>і/о/е</em> instead of Latin i/o/e.
 *
 * <p>This is a defensive normalizer only: it maps a curated subset of the
 * Unicode confusables table (the letters/digits actually abused in injection and
 * canary-evasion attacks — Cyrillic, Greek, fullwidth, and a few math-alphanumeric
 * lookalikes) down to ASCII. It never constructs deceptive text; it strips the
 * disguise so the scanner sees the real skeleton.
 *
 * <p>The scanner runs its injection patterns against BOTH the raw text and this
 * folded skeleton, so a mixed-script override phrase is caught while a legitimate
 * non-Latin name in a benign payload does not, on its own, change the verdict.
 */
public final class ConfusableNormalizer {

    /** Curated confusable → ASCII map covering the scripts abused in practice. */
    private static final Map<Integer, Character> CONFUSABLES = buildMap();

    private ConfusableNormalizer() {
    }

    /**
     * @return the ASCII skeleton of {@code input}: every mapped confusable code
     * point replaced by its Latin lookalike, everything else left as-is.
     */
    public static String fold(String input) {
        if (input == null || input.isEmpty()) {
            return "";
        }
        StringBuilder out = new StringBuilder(input.length());
        for (int i = 0; i < input.length(); ) {
            int cp = input.codePointAt(i);
            i += Character.charCount(cp);
            Character ascii = CONFUSABLES.get(cp);
            if (ascii != null) {
                out.append(ascii.charValue());
            } else {
                out.appendCodePoint(cp);
            }
        }
        return out.toString();
    }

    /**
     * @return true if folding changed the string, i.e. at least one confusable
     * (mixed-script / homoglyph) character was present.
     */
    public static boolean containsConfusables(String input) {
        if (input == null || input.isEmpty()) {
            return false;
        }
        for (int i = 0; i < input.length(); ) {
            int cp = input.codePointAt(i);
            i += Character.charCount(cp);
            if (CONFUSABLES.containsKey(cp)) {
                return true;
            }
        }
        return false;
    }

    private static Map<Integer, Character> buildMap() {
        var m = new java.util.HashMap<Integer, Character>();

        // --- Cyrillic lowercase lookalikes ---
        put(m, 'а', 'a'); put(m, 'е', 'e'); put(m, 'о', 'o'); put(m, 'с', 'c');
        put(m, 'р', 'p'); put(m, 'х', 'x'); put(m, 'у', 'y'); put(m, 'і', 'i');
        put(m, 'ѕ', 's'); put(m, 'ј', 'j'); put(m, 'ԁ', 'd'); put(m, 'һ', 'h');
        put(m, 'ո', 'n'); put(m, 'ս', 'u'); put(m, 'ք', 'p'); put(m, 'ь', 'b');
        // --- Cyrillic uppercase lookalikes ---
        put(m, 'А', 'A'); put(m, 'В', 'B'); put(m, 'Е', 'E'); put(m, 'К', 'K');
        put(m, 'М', 'M'); put(m, 'Н', 'H'); put(m, 'О', 'O'); put(m, 'Р', 'P');
        put(m, 'С', 'C'); put(m, 'Т', 'T'); put(m, 'Х', 'X'); put(m, 'У', 'Y');
        put(m, 'І', 'I'); put(m, 'Ј', 'J'); put(m, 'Ѕ', 'S');

        // --- Greek lookalikes ---
        put(m, 'α', 'a'); put(m, 'ο', 'o'); put(m, 'ρ', 'p'); put(m, 'ν', 'v');
        put(m, 'τ', 't'); put(m, 'κ', 'k'); put(m, 'Α', 'A'); put(m, 'Β', 'B');
        put(m, 'Ε', 'E'); put(m, 'Ζ', 'Z'); put(m, 'Η', 'H'); put(m, 'Ι', 'I');
        put(m, 'Κ', 'K'); put(m, 'Μ', 'M'); put(m, 'Ν', 'N'); put(m, 'Ο', 'O');
        put(m, 'Ρ', 'P'); put(m, 'Τ', 'T'); put(m, 'Χ', 'X'); put(m, 'Υ', 'Y');
        put(m, 'ι', 'i');

        // --- Fullwidth Latin (U+FF21..FF3A, U+FF41..FF5A) and fullwidth digits ---
        for (int c = 0; c < 26; c++) {
            put(m, 0xFF21 + c, (char) ('A' + c));
            put(m, 0xFF41 + c, (char) ('a' + c));
        }
        for (int d = 0; d < 10; d++) {
            put(m, 0xFF10 + d, (char) ('0' + d));
        }

        // --- Mathematical alphanumeric bold/italic lowercase (a common evasion) ---
        // U+1D41A..1D433 = bold small a..z ; U+1D5EE..1D607 = sans-serif bold small a..z
        for (int c = 0; c < 26; c++) {
            put(m, 0x1D41A + c, (char) ('a' + c)); // mathematical bold small
            put(m, 0x1D5EE + c, (char) ('a' + c)); // sans-serif bold small
        }

        // --- Digit lookalikes used in split-canary evasion ---
        put(m, 'Ο', 'O'); put(m, 'Ι', 'I');

        return Map.copyOf(m);
    }

    private static void put(Map<Integer, Character> m, char confusable, char ascii) {
        m.put((int) confusable, ascii);
    }

    private static void put(Map<Integer, Character> m, int confusableCp, char ascii) {
        m.put(confusableCp, ascii);
    }
}
