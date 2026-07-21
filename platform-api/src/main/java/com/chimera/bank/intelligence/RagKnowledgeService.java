package com.chimera.bank.intelligence;

import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Lightweight local retrieval index. It is intentionally transparent and
 * deterministic for validation; production RAG should use approved embeddings,
 * access controls, citations, and an evaluated vector store.
 */
@Service
public class RagKnowledgeService {
    public record Retrieval(String id, String source, String title, String excerpt, String techniqueId,
                            String techniqueName, double score) { }
    public record EvaluationCase(String query, String expectedSource, String expectedTechniqueId) { }
    public record EvaluationReport(int total, int topOneHits, int topThreeHits, double topOneAccuracy,
                                   double topThreeRecall, double meanReciprocalRank) { }

    private final CopyOnWriteArrayList<ThreatIntelligenceService.ThreatRecord> documents = new CopyOnWriteArrayList<>();

    public void index(List<ThreatIntelligenceService.ThreatRecord> source) {
        documents.clear();
        documents.addAll(source);
    }

    public List<Retrieval> search(String query, int limit) {
        Set<String> queryTerms = terms(query);
        if (queryTerms.isEmpty()) {
            return List.of();
        }
        return documents.stream().map(document -> toRetrieval(document, queryTerms))
                .filter(result -> result.score() > 0)
                .sorted(Comparator.comparing(Retrieval::score).reversed())
                .limit(Math.max(1, Math.min(limit, 10))).toList();
    }

    public EvaluationReport evaluate(List<EvaluationCase> cases) {
        if (cases == null || cases.isEmpty()) {
            return new EvaluationReport(0, 0, 0, 0, 0, 0);
        }
        int topOne = 0;
        int topThree = 0;
        double reciprocalRank = 0;
        for (EvaluationCase test : cases) {
            List<Retrieval> results = search(test.query(), 3);
            int rank = rank(results, test);
            if (rank == 1) topOne++;
            if (rank > 0) {
                topThree++;
                reciprocalRank += 1.0 / rank;
            }
        }
        int total = cases.size();
        return new EvaluationReport(total, topOne, topThree, round((double) topOne / total),
                round((double) topThree / total), round(reciprocalRank / total));
    }

    private static int rank(List<Retrieval> results, EvaluationCase test) {
        for (int i = 0; i < results.size(); i++) {
            Retrieval item = results.get(i);
            boolean sourceMatch = test.expectedSource() == null || test.expectedSource().isBlank()
                    || item.source().equalsIgnoreCase(test.expectedSource());
            boolean techniqueMatch = test.expectedTechniqueId() == null || test.expectedTechniqueId().isBlank()
                    || item.techniqueId().equalsIgnoreCase(test.expectedTechniqueId());
            if (sourceMatch && techniqueMatch) return i + 1;
        }
        return 0;
    }

    private static Retrieval toRetrieval(ThreatIntelligenceService.ThreatRecord document, Set<String> queryTerms) {
        String combined = (document.title() + " " + document.summary() + " " + document.source() + " "
                + document.techniqueId() + " " + document.techniqueName()).toLowerCase(Locale.ROOT);
        int matches = 0;
        for (String term : queryTerms) if (combined.contains(term)) matches++;
        double score = (double) matches / queryTerms.size();
        String excerpt = document.summary().length() > 280 ? document.summary().substring(0, 280) + "…" : document.summary();
        return new Retrieval(document.id(), document.source(), document.title(), excerpt,
                document.techniqueId(), document.techniqueName(), round(score));
    }

    private static Set<String> terms(String text) {
        if (text == null) return Set.of();
        Set<String> values = new LinkedHashSet<>();
        for (String term : text.toLowerCase(Locale.ROOT).split("[^a-z0-9-]+")) {
            if (term.length() >= 3) values.add(term);
        }
        return values;
    }

    private static double round(double value) {
        return Math.round(value * 10_000.0) / 10_000.0;
    }
    public double scoreHealingAccuracy(String attackType, String generatedPatch) {
    // In a real system, you compare the generated patch against a known-good database
    // For now, we check if the patch contains expected keywords for the attack type
    if (generatedPatch == null || generatedPatch.isEmpty()) return 0.0;
    
    if (attackType.equals("SQL_INJECTION") && generatedPatch.contains("parameterized") && generatedPatch.contains("WAF")) {
        return 95.0; // 95% accuracy score
    }
    if (attackType.equals("AI_BRUTE_FORCE") && generatedPatch.contains("rate_limit") && generatedPatch.contains("honeypot")) {
        return 92.0;
    }
    return 50.0; // Partial credit
}
}