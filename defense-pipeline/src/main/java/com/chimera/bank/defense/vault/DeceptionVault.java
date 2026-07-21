package com.chimera.bank.defense.vault;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The deception vault: an isolated, manager-only quarantine store.
 *
 * <p>When every outer ring has failed to stop or self-heal in time, the session
 * and the sensitive working set it touched are redirected here — an isolated,
 * encrypted store separate from production — so the real data is protected
 * behind a boundary the attacker's session can no longer reach. This is the
 * safe form of the requested "move data to a dummy secured DB" idea:
 *
 * <ul>
 *   <li><b>Reversible.</b> Quarantine snapshots are retained, not destroyed. A
 *       purge is a separate, explicit, manager-approved and audited action.</li>
 *   <li><b>Least authority.</b> Only MANAGER-tier nodes can list, restore, or
 *       approve purge of vault entries (enforced in platform-api).</li>
 *   <li><b>No hack-back.</b> The vault only relocates the bank's OWN data to a
 *       safe boundary; it never deletes or attacks any external party's data.</li>
 * </ul>
 *
 * <p>This in-memory implementation is a reference. Production replaces it with a
 * dedicated encrypted datastore with WORM audit and dual-control key custody.
 */
@Component
public class DeceptionVault {

    private static final Logger log = LoggerFactory.getLogger(DeceptionVault.class);

    public record VaultEntry(
            String vaultId,
            String correlationId,
            Instant quarantinedAt,
            String reason,
            Map<String, Object> snapshot,
            Status status) {
    }

    public enum Status {QUARANTINED, RESTORED, PURGE_PENDING, PURGED}

    private final Map<String, VaultEntry> store = new ConcurrentHashMap<>();

    /** Relocate a compromised session's working set into isolated quarantine. */
    public VaultEntry quarantine(String correlationId, String reason, Map<String, Object> snapshot) {
        String vaultId = "vault-" + UUID.randomUUID();
        VaultEntry entry = new VaultEntry(
                vaultId, correlationId, Instant.now(), reason,
                Map.copyOf(snapshot), Status.QUARANTINED);
        store.put(vaultId, entry);
        log.warn("Quarantined session {} into {} (reason={})", correlationId, vaultId, reason);
        return entry;
    }

    public List<VaultEntry> list() {
        return List.copyOf(store.values());
    }

    /** Reversible restore of a quarantined entry after human review clears it. */
    public VaultEntry restore(String vaultId) {
        VaultEntry e = require(vaultId);
        VaultEntry restored = new VaultEntry(
                e.vaultId(), e.correlationId(), e.quarantinedAt(), e.reason(), e.snapshot(), Status.RESTORED);
        store.put(vaultId, restored);
        log.info("Restored vault entry {}", vaultId);
        return restored;
    }

    /** Step 1 of a two-person purge: mark pending. Actual purge requires approval. */
    public VaultEntry requestPurge(String vaultId) {
        VaultEntry e = require(vaultId);
        VaultEntry pending = new VaultEntry(
                e.vaultId(), e.correlationId(), e.quarantinedAt(), e.reason(), e.snapshot(), Status.PURGE_PENDING);
        store.put(vaultId, pending);
        return pending;
    }

    /** Step 2: manager-approved, audited purge. Only permitted from PURGE_PENDING. */
    public VaultEntry approvePurge(String vaultId, String approverRegNo) {
        VaultEntry e = require(vaultId);
        if (e.status() != Status.PURGE_PENDING) {
            throw new IllegalStateException("Purge not pending for " + vaultId);
        }
        VaultEntry purged = new VaultEntry(
                e.vaultId(), e.correlationId(), e.quarantinedAt(),
                e.reason() + " | purged_by=" + approverRegNo, Map.of(), Status.PURGED);
        store.put(vaultId, purged);
        log.warn("Vault entry {} purged with approval by {}", vaultId, approverRegNo);
        return purged;
    }

    private VaultEntry require(String vaultId) {
        VaultEntry e = store.get(vaultId);
        if (e == null) {
            throw new IllegalArgumentException("Unknown vault entry: " + vaultId);
        }
        return e;
    }
}
