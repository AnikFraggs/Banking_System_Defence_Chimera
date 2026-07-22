package com.chimera.bank.service;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface SuggestionRepository extends JpaRepository<SuggestionEntity, Long> {
    List<SuggestionEntity> findTop50ByOrderByCreatedAtDesc();
}
