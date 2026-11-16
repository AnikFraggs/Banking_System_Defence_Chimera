package com.chimera.bank.defense;

import com.chimera.bank.audit.AuditCrypto;
import com.chimera.bank.defense.vault.DeceptionVault;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class JpaVaultPersistence implements DeceptionVault.VaultPersistence {
    private static final Logger log = LoggerFactory.getLogger(JpaVaultPersistence.class);

    private final DeceptionVaultRepository repository;
    private final AuditCrypto crypto;
    private final ObjectMapper objectMapper;

    public JpaVaultPersistence(DeceptionVaultRepository repository, AuditCrypto crypto, ObjectMapper objectMapper) {
        this.repository = repository;
        this.crypto = crypto;
        this.objectMapper = objectMapper;
    }

    @Override
    public void save(DeceptionVault.VaultEntry entry) {
        try {
            String snapshotJson = objectMapper.writeValueAsString(entry.snapshot());
            String encryptedSnapshot = crypto.encryptAesGcm(snapshotJson);
            DeceptionVaultEntity entity = new DeceptionVaultEntity(
                    entry.vaultId(),
                    entry.correlationId(),
                    entry.quarantinedAt(),
                    entry.reason(),
                    encryptedSnapshot,
                    entry.status().name()
            );
            repository.save(entity);
            log.info("Persisted vault entry {} to PostgreSQL deception_vault_entries with AES-256-GCM envelope encryption", entry.vaultId());
        } catch (Exception ex) {
            log.error("Failed to persist vault entry {}: {}", entry.vaultId(), ex.getMessage(), ex);
            throw new IllegalStateException("Failed to persist vault entry " + entry.vaultId(), ex);
        }
    }
}
