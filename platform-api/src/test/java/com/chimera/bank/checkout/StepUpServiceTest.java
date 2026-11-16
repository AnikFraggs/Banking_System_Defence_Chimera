package com.chimera.bank.checkout;

import com.chimera.bank.audit.AuditCrypto;
import org.junit.jupiter.api.Test;

import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class StepUpServiceTest {
    @Test
    void challengeIsSingleUseAndBoundToOrder() {
        StepUpChallengeRepository repository = mock(StepUpChallengeRepository.class);
        when(repository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));
        StepUpService service = new StepUpService(repository, new AuditCrypto("test-key-with-at-least-32-characters", "test"));
        UUID orderId = UUID.randomUUID();
        String code = service.issue(orderId);
        StepUpChallengeEntity challenge = new StepUpChallengeEntity();
        challenge.setOrderId(orderId);
        challenge.setCodeHash(new AuditCrypto("test-key-with-at-least-32-characters", "test").hmac(orderId + ":" + code));
        challenge.setExpiresAt(java.time.Instant.now().plusSeconds(60));
        when(repository.findByOrderId(orderId)).thenReturn(Optional.of(challenge));

        assertEquals(StepUpService.Verification.SUCCESS, service.verify(orderId, code));
        assertEquals(StepUpService.Verification.LOCKED, service.verify(orderId, code));
    }
}
