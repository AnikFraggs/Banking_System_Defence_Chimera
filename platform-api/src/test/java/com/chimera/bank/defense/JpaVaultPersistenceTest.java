package com.chimera.bank.defense;

import com.chimera.bank.audit.AuditCrypto;
import com.chimera.bank.defense.vault.DeceptionVault;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Instant;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class JpaVaultPersistenceTest {

    @Test
    void persistsEncryptedVaultEntry() {
        DeceptionVaultRepository repository = mock(DeceptionVaultRepository.class);
        AuditCrypto crypto = new AuditCrypto("test-encryption-key-with-32-bytes!", "test");
        ObjectMapper mapper = new ObjectMapper();
        JpaVaultPersistence persistence = new JpaVaultPersistence(repository, crypto, mapper);

        DeceptionVault.VaultEntry entry = new DeceptionVault.VaultEntry(
                "vault-123",
                "cor-456",
                Instant.now(),
                "test-suspicion",
                Map.of("sensitive_signal", "secret_value"),
                DeceptionVault.Status.QUARANTINED
        );

        persistence.save(entry);

        ArgumentCaptor<DeceptionVaultEntity> captor = ArgumentCaptor.forClass(DeceptionVaultEntity.class);
        verify(repository).save(captor.capture());

        DeceptionVaultEntity saved = captor.getValue();
        assertEquals("vault-123", saved.getVaultId());
        assertEquals("cor-456", saved.getCorrelationId());
        assertEquals("QUARANTINED", saved.getStatus());
        assertNotEquals("secret_value", saved.getEncryptedSnapshot());

        String decrypted = crypto.decryptAesGcm(saved.getEncryptedSnapshot());
        assertTrue(decrypted.contains("secret_value"));
    }
}
