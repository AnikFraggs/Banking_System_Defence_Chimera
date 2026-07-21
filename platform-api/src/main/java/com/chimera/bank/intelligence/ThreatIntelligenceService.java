package com.chimera.bank.intelligence;

import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Curates defensive threat intelligence. It consumes only structured public
 * vulnerability metadata and ATT&CK technique context; it never downloads,
 * stores, or trains on exploit code or attack-lab payloads.
 */
@Service
@SuppressWarnings("unchecked")
public class ThreatIntelligenceService {
    public record Source(String id, String name, String url, String purpose, String ingestionMode,
                         boolean referenceOnly) { }
    public record ThreatRecord(String id, String source, String title, String summary, String severity,
                               String techniqueId, String techniqueName, Instant observedAt) { }
    public record RefreshReport(Instant refreshedAt, int imported, List<String> completedSources,
                                List<String> warnings) { }

    private static final List<Source> SOURCES = List.of(
            new Source("kaggle", "Kaggle (operator-provided labeled CSV)", "https://www.kaggle.com/datasets",
                    "Labeled validation data after license and schema review", "local-upload-only", false),
            new Source("mitre_attack", "MITRE ATT&CK", "https://attack.mitre.org/",
                    "Map observations to tactics and techniques", "curated-technique-taxonomy", false),
            new Source("cisa_kev", "CISA Known Exploited Vulnerabilities", "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                    "Prioritize vulnerabilities known to be exploited", "structured-json", false),
            new Source("nvd", "NIST National Vulnerability Database", "https://nvd.nist.gov/developers/vulnerabilities",
                    "CVE/CVSS and weakness enrichment", "structured-json", false),
            new Source("owasp", "OWASP", "https://owasp.org/", "Defensive guidance and taxonomy", "reference-link", true),
            new Source("portswigger", "PortSwigger Web Security Academy", "https://portswigger.net/web-security",
                    "Authorized training reference only; no automated lab scraping", "reference-link", true),
            new Source("juice_shop", "OWASP Juice Shop", "https://owasp.org/www-project-juice-shop/",
                    "Local, intentionally vulnerable practice application reference", "reference-link", true));

    private final RestClient http = RestClient.builder().build();
    private final CopyOnWriteArrayList<ThreatRecord> records = new CopyOnWriteArrayList<>();
    private final RagKnowledgeService rag;

    public ThreatIntelligenceService(RagKnowledgeService rag) {
        this.rag = rag;
        // Small reviewed technique seed is available offline; refresh adds CVE/KEV metadata.
        records.addAll(List.of(
                new ThreatRecord("T1566", "MITRE ATT&CK", "Phishing", "Credential-access social engineering behavior.",
                        "HIGH", "T1566", "Phishing", Instant.EPOCH),
                new ThreatRecord("T1078", "MITRE ATT&CK", "Valid Accounts", "Use of legitimate credentials in adversary activity.",
                        "HIGH", "T1078", "Valid Accounts", Instant.EPOCH),
                new ThreatRecord("T1190", "MITRE ATT&CK", "Exploit Public-Facing Application",
                        "Technique context for detecting exposure; no exploit content is retained.", "HIGH",
                        "T1190", "Exploit Public-Facing Application", Instant.EPOCH)));
        rag.index(records);
    }

    public List<Source> sources() {
        return SOURCES;
    }

    public List<ThreatRecord> records() {
        return records.stream().sorted(Comparator.comparing(ThreatRecord::observedAt).reversed()).limit(100).toList();
    }

    public synchronized RefreshReport refresh() {
        List<ThreatRecord> fresh = new ArrayList<>();
        List<String> completed = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        try {
            fresh.addAll(fetchKev());
            completed.add("cisa_kev");
        } catch (Exception e) {
            warnings.add("CISA KEV unavailable: " + concise(e));
        }
        try {
            fresh.addAll(fetchNvd());
            completed.add("nvd");
        } catch (Exception e) {
            warnings.add("NVD unavailable: " + concise(e));
        }
        if (!fresh.isEmpty()) {
            records.removeIf(record -> record.source().equals("CISA KEV") || record.source().equals("NVD"));
            records.addAll(fresh);
            rag.index(records);
        }
        return new RefreshReport(Instant.now(), fresh.size(), completed, warnings);
    }

    private List<ThreatRecord> fetchKev() {
        Map<String, Object> body = http.get()
                .uri("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")
                .retrieve()
                .onStatus(HttpStatusCode::isError, (req, res) -> { throw new IllegalStateException("HTTP " + res.getStatusCode()); })
                .body(Map.class);
        List<Map<String, Object>> vulnerabilities = body == null ? List.of() : (List<Map<String, Object>>) body.getOrDefault("vulnerabilities", List.of());
        return vulnerabilities.stream().limit(25).map(item -> new ThreatRecord(
                string(item.get("cveID")), "CISA KEV", string(item.get("vulnerabilityName")),
                string(item.get("shortDescription")), "KNOWN_EXPLOITED", "T1190", "Exploit Public-Facing Application",
                Instant.now())).toList();
    }

    private List<ThreatRecord> fetchNvd() {
        Map<String, Object> body = http.get()
                .uri("https://services.nvd.nist.gov/rest/json/cves/2.0?hasKev&resultsPerPage=25")
                .retrieve()
                .onStatus(HttpStatusCode::isError, (req, res) -> { throw new IllegalStateException("HTTP " + res.getStatusCode()); })
                .body(Map.class);
        List<Map<String, Object>> vulnerabilities = body == null ? List.of() : (List<Map<String, Object>>) body.getOrDefault("vulnerabilities", List.of());
        List<ThreatRecord> result = new ArrayList<>();
        for (Map<String, Object> item : vulnerabilities) {
            Map<String, Object> cve = (Map<String, Object>) item.getOrDefault("cve", Map.of());
            String id = string(cve.get("id"));
            List<Map<String, Object>> descriptions = (List<Map<String, Object>>) cve.getOrDefault("descriptions", List.of());
            String description = descriptions.stream().filter(d -> "en".equals(d.get("lang")))
                    .map(d -> string(d.get("value"))).findFirst().orElse("No English description supplied.");
            result.add(new ThreatRecord(id, "NVD", id, description, cvssSeverity(cve), "T1190",
                    "Exploit Public-Facing Application", Instant.now()));
        }
        return result;
    }

    private static String cvssSeverity(Map<String, Object> cve) {
        try {
            Map<String, Object> metrics = (Map<String, Object>) cve.get("metrics");
            List<Map<String, Object>> v31 = (List<Map<String, Object>>) metrics.get("cvssMetricV31");
            Map<String, Object> cvss = (Map<String, Object>) v31.getFirst().get("cvssData");
            return string(cvss.get("baseSeverity"));
        } catch (RuntimeException e) {
            return "UNKNOWN";
        }
    }

    private static String string(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static String concise(Exception e) {
        String message = e.getMessage();
        return message == null ? e.getClass().getSimpleName() : message.replaceAll("[\\r\\n]", " ");
    }
}