package com.chimera.bank.banking;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface TransactionRepository extends JpaRepository<TransactionEntity, Long> {
    List<TransactionEntity> findTop10ByUsernameOrderByTimestampDesc(String username);
}