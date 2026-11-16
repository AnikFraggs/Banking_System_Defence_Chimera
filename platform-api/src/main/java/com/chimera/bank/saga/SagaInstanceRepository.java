package com.chimera.bank.saga;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface SagaInstanceRepository extends JpaRepository<SagaInstanceEntity, UUID> {
}