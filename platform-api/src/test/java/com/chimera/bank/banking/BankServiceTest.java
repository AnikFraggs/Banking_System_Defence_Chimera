package com.chimera.bank.banking;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.auth.UserRepository;
import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.DefensePipeline;
import com.chimera.bank.defense.DefenseResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Instant;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class BankServiceTest {

    private UserRepository userRepository;
    private TransactionRepository transactionRepository;
    private DefensePipeline defense;
    private BankService bankService;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        transactionRepository = mock(TransactionRepository.class);
        defense = mock(DefensePipeline.class);
        bankService = new BankService(userRepository, transactionRepository, defense);
    }

    @Test
    void getSecurityChallengeReturnsValidChallenge() {
        BankService.SecurityChallenge challenge = bankService.getSecurityChallenge();
        assertNotNull(challenge);
        assertNotNull(challenge.question());
        assertNotNull(challenge.expectedAnswer());
    }

    @Test
    void validateSecureTransferGeneratesSixDigitOtpWhenAllowed() {
        AuthService.Principal principal = new AuthService.Principal(
                "CUST-1001", "Alice", Role.CUSTOMER, Instant.now().plusSeconds(3600));

        DefenseResult allowedResult = mock(DefenseResult.class);
        when(allowedResult.allowed()).thenReturn(true);
        when(defense.evaluate(any(DefenseContext.class))).thenReturn(allowedResult);

        BankService.SecureTransferResponse resp = bankService.validateSecureTransfer(
                principal, "blue", "Bob", new BigDecimal("500.00"));

        assertEquals("SECURE", resp.status());
        assertNotNull(resp.otp());
        assertEquals(6, resp.otp().length());
        assertTrue(resp.otp().matches("^\\d{6}$"));
    }

    @Test
    void validateSecureTransferQuarantinesOnAiTriggerAnswer() {
        AuthService.Principal principal = new AuthService.Principal(
                "CUST-1001", "Alice", Role.CUSTOMER, Instant.now().plusSeconds(3600));

        BankService.SecureTransferResponse resp = bankService.validateSecureTransfer(
                principal, "999", "Bob", new BigDecimal("500.00"));

        assertEquals("QUARANTINED", resp.status());
        assertNull(resp.otp());
        verify(defense, never()).evaluate(any());
    }
}
