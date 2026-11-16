package com.chimera.bank.defense;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface DeceptionVaultRepository extends JpaRepository<DeceptionVaultEntity, String> {
    Optional<DeceptionVaultEntity> findByVaultId(String vaultId);
}
