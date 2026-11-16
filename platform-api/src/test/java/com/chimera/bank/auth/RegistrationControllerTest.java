package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class RegistrationControllerTest {

    private UserRepository userRepository;
    private RegistrationController controller;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        controller = new RegistrationController(userRepository);
    }

    @Test
    void registerEnforcesCustomerRoleEvenIfManagerRequested() {
        when(userRepository.findByUsername("attacker")).thenReturn(Optional.empty());
        when(userRepository.save(any(AppUser.class))).thenAnswer(invocation -> invocation.getArgument(0));

        RegistrationController.RegistrationRequest req = new RegistrationController.RegistrationRequest(
                "attacker",
                "SecretPassword123!",
                "Attacker User",
                "MANAGER" // Attempting privilege escalation
        );

        ResponseEntity<Map<String, String>> response = controller.register(req);

        assertEquals(HttpStatus.CREATED, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals("SUCCESS", response.getBody().get("status"));
        assertEquals("CUSTOMER", response.getBody().get("role"));
        assertEquals("attacker", response.getBody().get("username"));

        ArgumentCaptor<AppUser> captor = ArgumentCaptor.forClass(AppUser.class);
        verify(userRepository).save(captor.capture());
        AppUser savedUser = captor.getValue();
        assertEquals(Role.CUSTOMER.name(), savedUser.getRole(), "User role must strictly be locked to CUSTOMER");
        assertEquals("attacker", savedUser.getUsername());
        assertNotNull(savedUser.getAccountNumber());
        assertTrue(savedUser.getAccountNumber().startsWith("CHM-"));
    }

    @Test
    void registerRejectsDuplicateUsernameWithConflict() {
        AppUser existing = new AppUser();
        existing.setUsername("existinguser");
        when(userRepository.findByUsername("existinguser")).thenReturn(Optional.of(existing));

        RegistrationController.RegistrationRequest req = new RegistrationController.RegistrationRequest(
                "existinguser",
                "ValidPassword123!",
                "Existing User",
                null
        );

        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () -> controller.register(req));
        assertEquals(HttpStatus.CONFLICT, ex.getStatusCode());
        assertTrue(ex.getReason().contains("already exists"));
        verify(userRepository, never()).save(any());
    }

    @Test
    void registerWithNullCustomerNameDefaultsToUsername() {
        when(userRepository.findByUsername("simpleuser")).thenReturn(Optional.empty());
        when(userRepository.save(any(AppUser.class))).thenAnswer(invocation -> invocation.getArgument(0));

        RegistrationController.RegistrationRequest req = new RegistrationController.RegistrationRequest(
                "simpleuser",
                "ValidPassword123!",
                null,
                null
        );

        ResponseEntity<Map<String, String>> response = controller.register(req);
        assertEquals(HttpStatus.CREATED, response.getStatusCode());

        ArgumentCaptor<AppUser> captor = ArgumentCaptor.forClass(AppUser.class);
        verify(userRepository).save(captor.capture());
        assertEquals("simpleuser", captor.getValue().getCustomerName());
    }
}
