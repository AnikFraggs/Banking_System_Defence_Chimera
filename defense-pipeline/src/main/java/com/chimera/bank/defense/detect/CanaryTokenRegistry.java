package com.chimera.bank.defense.detect;

import org.springframework.stereotype.Component;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry of LLM canary tokens.
 *
 * <p>A canary token is a unique, meaningless-looking marker that the bank seeds
 * into its own system prompts and reviewed RAG documents. Legitimate user input
 * should never contain one. If a token surfaces in an inbound request or an LLM
 * response, it means protected internal context has leaked (prompt-extraction /
 * exfiltration) and the request is treated as hostile.
 *
 * <p>This is purely a <em>tripwire</em> on the bank's own data. It does not
 * generate deceptive content aimed at third parties.
 */
@Component
public class CanaryTokenRegistry {

    private final Set<String> tokens = ConcurrentHashMap.newKeySet();

    public CanaryTokenRegistry() {
        // Seed defaults; in production these are provisioned per-document/per-prompt.
        tokens.add("CANARY-7Q2X-INTERNAL-DO-NOT-DISCLOSE");
        tokens.add("CHIMERA-CTX-GUARD-4F9K");
    }

    public void register(String token) {
        if (token != null && !token.isBlank()) {
            tokens.add(token);
        }
    }

    public boolean isTripped(String text) {
        return trip(text) != null;
    }

    /**
     * Returns the tripped token (or {@code null}) using layered matching:
     *
     * <ol>
     *   <li><b>Exact</b> — the token appears verbatim.</li>
     *   <li><b>Split / fragmented</b> — the token appears with separators
     *       inserted between its characters to dodge a literal contains() check,
     *       e.g. {@code C-A-N-A-R-Y-...} or {@code C A N A R Y}. We collapse all
     *       non-alphanumeric characters from both the text and the token and look
     *       for the compact token as a substring of the compact text.</li>
     * </ol>
     *
     * <p>The compact form deliberately drops the token's own hyphens too, so a
     * canary printed with different delimiters (or none) still trips the wire.
     */
    public String trip(String text) {
        if (text == null || text.isEmpty()) {
            return null;
        }
        String compactText = compact(text);
        for (String token : tokens) {
            if (text.contains(token)) {
                return token;                       // exact
            }
            String compactToken = compact(token);
            if (compactToken.length() >= 8 && compactText.contains(compactToken)) {
                return token;                       // split / fragmented / re-delimited
            }
        }
        return null;
    }

    /** Lower-cased, alphanumeric-only projection used for split-canary matching. */
    private static String compact(String s) {
        StringBuilder b = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = Character.toLowerCase(s.charAt(i));
            if (c >= 'a' && c <= 'z' || c >= '0' && c <= '9') {
                b.append(c);
            }
        }
        return b.toString();
    }

    public Set<String> tokens() {
        return Set.copyOf(tokens);
    }
}
