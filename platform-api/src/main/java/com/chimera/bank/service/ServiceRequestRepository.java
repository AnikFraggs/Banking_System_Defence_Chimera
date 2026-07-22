package com.chimera.bank.service;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ServiceRequestRepository extends JpaRepository<ServiceRequestEntity, Long> {
    List<ServiceRequestEntity> findByUsernameOrderByCreatedAtDesc(String username);
    List<ServiceRequestEntity> findByStatusOrderByCreatedAtDesc(String status);
    List<ServiceRequestEntity> findAllByOrderByCreatedAtDesc();
}
