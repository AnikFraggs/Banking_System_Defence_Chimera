package com.chimera.bank.intelligence;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** Analyst/manager interfaces for approved intelligence and retrieval evaluation. */
@RestController
@RequestMapping("/api/intelligence")
public class IntelligenceController {
    private final AuthService auth;
    private final ThreatIntelligenceService intelligence;
    private final RagKnowledgeService rag;

    public IntelligenceController(AuthService auth, ThreatIntelligenceService intelligence, RagKnowledgeService rag) {
        this.auth = auth;
        this.intelligence = intelligence;
        this.rag = rag;
    }

    public record QueryBody(@NotBlank String query, Integer limit) { }

    @GetMapping("/sources")
    public List<ThreatIntelligenceService.Source> sources(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return intelligence.sources();
    }

    @GetMapping("/records")
    public List<ThreatIntelligenceService.ThreatRecord> records(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.ACCOUNTANT, Role.MANAGER);
        return intelligence.records();
    }

    @PostMapping("/refresh")
    public ThreatIntelligenceService.RefreshReport refresh(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return intelligence.refresh();
    }

    @PostMapping("/rag/query")
    public List<RagKnowledgeService.Retrieval> query(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @Valid @RequestBody QueryBody body) {
        auth.require(authorization);
        return rag.search(body.query(), body.limit() == null ? 5 : body.limit());
    }

    @PostMapping("/rag/evaluate")
    public RagKnowledgeService.EvaluationReport evaluateRag(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody List<RagKnowledgeService.EvaluationCase> cases) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return rag.evaluate(cases);
    }
}