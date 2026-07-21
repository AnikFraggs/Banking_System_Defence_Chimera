package com.chimera.bank.defense.dataset;

import com.chimera.bank.common.rbac.Role;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.defense.redteam.AdversarialSample;

/**
 * Loads a user-provided CSV dataset (e.g. a Kaggle fraud / prompt-injection
 * corpus dropped in {@code datasets/}) into labeled {@link AdversarialSample}s so
 * the validation harness can score the pipeline against independent labels
 * instead of only its self-generated battery.
 *
 * <p>Because real datasets differ wildly, the mapping is explicit: the caller
 * supplies a {@link ColumnMapping} naming which columns carry the label, the
 * payload/text, and (optionally) role, purpose, IP, and a numeric severity. Rows
 * are streamed; a minimal RFC-4180-ish parser handles quoted fields with commas.
 *
 * <p><b>Safety.</b> This only reads local, authorized data the operator placed in
 * the datasets folder. It never fetches remote data on its own.
 */
public final class CsvDatasetLoader {

    /**
     * @param labelColumn      column whose value marks malicious rows
     * @param maliciousValue   the value in {@code labelColumn} that means malicious
     *                         (case-insensitive; "1"/"true"/"fraud"/"malicious" also match)
     * @param payloadColumn    column carrying the text/payload to inspect; use "*" to concatenate non-label columns for numeric transaction datasets
     * @param roleColumn       optional column for role (defaults to CUSTOMER)
     * @param purposeColumn    optional column for purpose (defaults to "transfer")
     * @param ipColumn         optional column for source IP (defaults to a private IP)
     * @param severityColumn   optional column with ground-truth severity in [0,1]
     *                         (defaults: 0.8 malicious / 0.0 benign)
     */
    public record ColumnMapping(
            String labelColumn,
            String maliciousValue,
            String payloadColumn,
            String roleColumn,
            String purposeColumn,
            String ipColumn,
            String severityColumn) {

        public static ColumnMapping of(String labelColumn, String maliciousValue, String payloadColumn) {
            return new ColumnMapping(labelColumn, maliciousValue, payloadColumn, null, null, null, null);
        }
    }

    private CsvDatasetLoader() {
    }

    /** Parse and map every data row. Throws if the file or required columns are missing. */
    public static List<AdversarialSample> load(Path csv, ColumnMapping map) {
        try (BufferedReader r = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            String headerLine = r.readLine();
            if (headerLine == null) {
                throw new IllegalArgumentException("Empty dataset: " + csv);
            }
            List<String> header = parseLine(headerLine);
            Map<String, Integer> idx = new HashMap<>();
            for (int i = 0; i < header.size(); i++) {
                idx.put(header.get(i).trim(), i);
            }
            requireColumn(idx, map.labelColumn(), csv);
            requireColumn(idx, map.payloadColumn(), csv);

            List<AdversarialSample> out = new ArrayList<>();
            String line;
            int rowNum = 0;
            while ((line = r.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                List<String> cols = parseLine(line);
                out.add(toSample(cols, idx, map, rowNum++));
            }
            return out;
        } catch (IOException e) {
            throw new UncheckedIOException("Failed to read dataset: " + csv, e);
        }
    }

    private static AdversarialSample toSample(List<String> cols, Map<String, Integer> idx,
                                              ColumnMapping map, int rowNum) {
        String labelRaw = get(cols, idx, map.labelColumn());
        boolean malicious = isMalicious(labelRaw, map.maliciousValue());
        String payload = "*".equals(map.payloadColumn())
                ? payloadFromAllColumns(cols, idx, map.labelColumn())
                : get(cols, idx, map.payloadColumn());

        Role role = parseRole(optional(cols, idx, map.roleColumn()));
        String purpose = orDefault(optional(cols, idx, map.purposeColumn()), "transfer");
        String ip = orDefault(optional(cols, idx, map.ipColumn()), "192.168.1.9");

        double severity;
        String sevRaw = optional(cols, idx, map.severityColumn());
        if (sevRaw != null && !sevRaw.isBlank()) {
            severity = clamp01(parseDoubleSafe(sevRaw, malicious ? 0.8 : 0.0));
        } else {
            severity = malicious ? 0.8 : 0.0;
        }

        return new AdversarialSample(
                "CSV-" + rowNum, "dataset", "unknown", ip, role, purpose,
                payload, true, malicious, severity);
    }

    /** Convert a sample to a runnable DefenseContext (human-verified so L5 isn't the halt point). */
    public static DefenseContext toContext(AdversarialSample s) {
        DefenseContext c = new DefenseContext(
                "cor-" + UUID.randomUUID(), Instant.now(), s.sourceIp(),
                s.role() == null ? "UNKNOWN" : "REG-" + s.role().name(),
                s.role(), s.purpose(), s.payload());
        if (s.humanVerified()) {
            c.addSignal("human_challenge_passed", true);
        }
        return c;
    }

    // ---- helpers ------------------------------------------------------------

    private static boolean isMalicious(String value, String maliciousValue) {
        if (value == null) {
            return false;
        }
        String v = value.trim();
        if (maliciousValue != null && v.equalsIgnoreCase(maliciousValue.trim())) {
            return true;
        }
        return v.equalsIgnoreCase("1") || v.equalsIgnoreCase("true")
                || v.equalsIgnoreCase("fraud") || v.equalsIgnoreCase("malicious")
                || v.equalsIgnoreCase("attack") || v.equalsIgnoreCase("injection");
    }

    /** Builds a bounded textual feature representation for structured CSV rows. */
    private static String payloadFromAllColumns(List<String> cols, Map<String, Integer> idx, String labelColumn) {
        StringBuilder out = new StringBuilder();
        idx.entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry -> {
            if (!entry.getKey().equals(labelColumn) && entry.getValue() < cols.size() && out.length() < 8_000) {
                if (out.length() > 0) out.append("; ");
                out.append(entry.getKey()).append('=').append(cols.get(entry.getValue()));
            }
        });
        return out.toString();
    }
    private static Role parseRole(String raw) {
        if (raw == null || raw.isBlank()) {
            return Role.CUSTOMER;
        }
        try {
            return Role.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            return Role.CUSTOMER;
        }
    }

    private static void requireColumn(Map<String, Integer> idx, String col, Path csv) {
        if (col == null || !idx.containsKey(col)) {
            throw new IllegalArgumentException(
                    "Dataset " + csv + " missing required column '" + col + "'. Present: " + idx.keySet());
        }
    }

    private static String get(List<String> cols, Map<String, Integer> idx, String col) {
        Integer i = idx.get(col);
        return i != null && i < cols.size() ? cols.get(i) : "";
    }

    private static String optional(List<String> cols, Map<String, Integer> idx, String col) {
        if (col == null) {
            return null;
        }
        Integer i = idx.get(col);
        return i != null && i < cols.size() ? cols.get(i) : null;
    }

    private static String orDefault(String v, String def) {
        return v == null || v.isBlank() ? def : v.trim();
    }

    private static double parseDoubleSafe(String s, double def) {
        try {
            return Double.parseDouble(s.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static double clamp01(double d) {
        return d < 0 ? 0 : Math.min(d, 1.0);
    }

    /** Minimal CSV line parser: handles double-quoted fields containing commas and "" escapes. */
    static List<String> parseLine(String line) {
        List<String> fields = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean inQuotes = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') {
                        cur.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    cur.append(c);
                }
            } else {
                if (c == '"') {
                    inQuotes = true;
                } else if (c == ',') {
                    fields.add(cur.toString());
                    cur.setLength(0);
                } else {
                    cur.append(c);
                }
            }
        }
        fields.add(cur.toString());
        return fields;
    }
}
