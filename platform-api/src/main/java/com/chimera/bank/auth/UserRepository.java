package com.chimera.bank.auth;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface UserRepository extends JpaRepository<AppUser, Long> {
    Optional<AppUser> findByUsername(String username);
    Optional<AppUser> findByAccountNumber(String accountNumber);
    java.util.List<AppUser> findByCustomerNameIgnoreCase(String customerName);
}