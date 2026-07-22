package com.chimera.bank.service;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.List;

/**
 * Read-only clients can leave advisory suggestion messages. Any signed-in role
 * may read them; only a client authors them.
 */
@RestController
@RequestMapping("/api/suggestions")
public class SuggestionController {

    private final AuthService auth;
    private final SuggestionRepository repository;

    public SuggestionController(AuthService auth, SuggestionRepository repository) {
        this.auth = auth;
        this.repository = repository;
    }

    public record NewSuggestion(@NotBlank String message, String toCustomer) { }

    @PostMapping
    public SuggestionEntity create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @Valid @RequestBody NewSuggestion body) {
        AuthService.Principal client = auth.requireOneOf(authorization, Role.CUSTOMER);
        SuggestionEntity entity = new SuggestionEntity();
        entity.setAuthorUsername(client.registrationNumber());
        entity.setAuthorName(client.displayName());
        entity.setToCustomer(body.toCustomer() == null ? "" : body.toCustomer().trim());
        entity.setMessage(body.message().trim());
        entity.setCreatedAt(Instant.now());
        return repository.save(entity);
    }

    @GetMapping
    public List<SuggestionEntity> list(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return repository.findTop50ByOrderByCreatedAtDesc();
    }
}
