package com.chimera.bank.defense.vault;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DeceptionVaultTest {

    @Test
    void everyTransitionIsPersisted() {
        List<DeceptionVault.VaultEntry> saved = new ArrayList<>();
        DeceptionVault vault = new DeceptionVault(Optional.of(saved::add));

        DeceptionVault.VaultEntry entry = vault.quarantine("cor-1", "test", Map.of("k", "v"));
        vault.requestPurge(entry.vaultId());
        vault.approvePurge(entry.vaultId(), "MGR-1");

        assertEquals(List.of(DeceptionVault.Status.QUARANTINED, DeceptionVault.Status.PURGE_PENDING,
                        DeceptionVault.Status.PURGED),
                saved.stream().map(DeceptionVault.VaultEntry::status).toList());
        assertTrue(saved.get(2).snapshot().isEmpty(), "purge must also wipe the durable snapshot");
    }

    @Test
    void durabilityFailureDoesNotUndoQuarantine() {
        DeceptionVault vault = new DeceptionVault(Optional.of(e -> {
            throw new IllegalStateException("db down");
        }));

        DeceptionVault.VaultEntry entry = vault.quarantine("cor-2", "test", Map.of("k", "v"));

        assertEquals(DeceptionVault.Status.QUARANTINED, entry.status());
        assertEquals(List.of(entry), vault.list());
    }
}
