package com.chimera.bank.checkout;

import com.chimera.bank.audit.AuditCrypto;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;

@Service
public class StepUpService {
    public enum Verification { SUCCESS, INVALID, EXPIRED, LOCKED }
    public record IssuedChallenge(String demoAnswer, String expectedAnswer,
                                  CheckoutDtos.VerificationChallengeView challenge) {}

    static final String OTP = "OTP";
    static final String INVOICE_DISCREPANCY = "INVOICE_DISCREPANCY";
    private static final int MAX_ATTEMPTS = 3;

    private final StepUpChallengeRepository repository;
    private final AuditCrypto crypto;
    private final VerificationChallengeGenerator generator;
    private final boolean exposeDemoAnswers;
    private final SecureRandom random = new SecureRandom();

    /** Offline compatibility constructor for the original OTP tests. */
    public StepUpService(StepUpChallengeRepository repository, AuditCrypto crypto) {
        this(repository, crypto, new DeterministicVerificationChallengeGenerator(), false);
    }

    @Autowired
    public StepUpService(StepUpChallengeRepository repository, AuditCrypto crypto,
                         VerificationChallengeGenerator generator,
                         @Value("${chimera.checkout.step-up.expose-demo-answers:false}") boolean exposeDemoAnswers) {
        this.repository = repository;
        this.crypto = crypto;
        this.generator = generator;
        this.exposeDemoAnswers = exposeDemoAnswers;
    }

    /** Original internal API retained for OTP tests and non-checkout callers. */
    @Transactional
    public String issue(UUID orderId) {
        return issueOtp(orderId, false).expectedAnswer();
    }

    @Transactional
    public IssuedChallenge issueOtp(UUID orderId, boolean simulated) {
        String code = String.format("%06d", random.nextInt(1_000_000));
        StepUpChallengeEntity challenge = reusable(orderId);
        challenge.setCodeHash(crypto.hmac(orderId + ":" + code));
        challenge.setChallengeType(OTP);
        challenge.setPrompt("Enter the six-digit verification code for order " + orderId + ".");
        clearInvoice(challenge);
        reset(challenge);
        repository.save(challenge);
        return issued(challenge, code, simulated);
    }

    @Transactional
    public IssuedChallenge issueInvoiceDiscrepancy(UUID orderId, InvoiceDiscrepancy discrepancy,
                                                    boolean simulated) {
        VerificationChallengeGenerator.GeneratedChallenge generated = generator.generate(orderId, discrepancy);
        StepUpChallengeEntity challenge = reusable(orderId);
        challenge.setChallengeType(INVOICE_DISCREPANCY);
        challenge.setPrompt(generated.prompt());
        challenge.setInvoiceOrderAmount(discrepancy.orderAmountText());
        challenge.setInvoiceAmount(discrepancy.invoiceAmountText());
        challenge.setInvoiceCurrency(discrepancy.currency());
        challenge.setCodeHash(crypto.hmac(invoiceSignaturePayload(orderId, challenge, generated.expectedAnswer())));
        reset(challenge);
        repository.save(challenge);
        return issued(challenge, generated.expectedAnswer(), simulated);
    }

    @Transactional
    public Verification verify(UUID orderId, String code) {
        StepUpChallengeEntity challenge = repository.findByOrderId(orderId).orElse(null);
        if (challenge == null || challenge.getConsumedAt() != null || challenge.getAttempts() >= MAX_ATTEMPTS) {
            return Verification.LOCKED;
        }
        if (challenge.getExpiresAt().isBefore(Instant.now())) return Verification.EXPIRED;

        boolean invoice = INVOICE_DISCREPANCY.equals(challenge.getChallengeType());
        String candidate = invoice ? normalizeInvoiceAnswer(code) : code;
        String payload = invoice
                ? candidate == null ? "" : invoiceSignaturePayload(orderId, challenge, candidate)
                : orderId + ":" + code;
        if (candidate == null || !crypto.validSignature(payload, challenge.getCodeHash())) {
            challenge.setAttempts(challenge.getAttempts() + 1);
            repository.save(challenge);
            return challenge.getAttempts() >= MAX_ATTEMPTS ? Verification.LOCKED : Verification.INVALID;
        }
        challenge.setConsumedAt(Instant.now());
        repository.save(challenge);
        return Verification.SUCCESS;
    }

    @Transactional(readOnly = true)
    public Optional<CheckoutDtos.VerificationChallengeView> currentChallenge(UUID orderId) {
        return repository.findByOrderId(orderId)
                .filter(challenge -> challenge.getConsumedAt() == null)
                .map(challenge -> view(challenge, null));
    }

    private StepUpChallengeEntity reusable(UUID orderId) {
        StepUpChallengeEntity challenge = repository.findByOrderId(orderId).orElseGet(StepUpChallengeEntity::new);
        challenge.setOrderId(orderId);
        return challenge;
    }

    private static void reset(StepUpChallengeEntity challenge) {
        challenge.setExpiresAt(Instant.now().plus(5, ChronoUnit.MINUTES));
        challenge.setAttempts(0);
        challenge.setConsumedAt(null);
    }

    private static void clearInvoice(StepUpChallengeEntity challenge) {
        challenge.setInvoiceOrderAmount(null);
        challenge.setInvoiceAmount(null);
        challenge.setInvoiceCurrency(null);
    }

    private IssuedChallenge issued(StepUpChallengeEntity challenge, String answer, boolean simulated) {
        String demoAnswer = exposeDemoAnswers && simulated ? answer : null;
        return new IssuedChallenge(demoAnswer, answer, view(challenge, demoAnswer));
    }

    private static CheckoutDtos.VerificationChallengeView view(StepUpChallengeEntity challenge, String demoAnswer) {
        boolean invoice = INVOICE_DISCREPANCY.equals(challenge.getChallengeType());
        return new CheckoutDtos.VerificationChallengeView(
                invoice ? INVOICE_DISCREPANCY : OTP,
                challenge.getPrompt(),
                challenge.getExpiresAt(),
                Math.max(0, MAX_ATTEMPTS - challenge.getAttempts()),
                demoAnswer,
                demoAnswer == null ? null : "SIMULATOR DEMO ANSWER ONLY — not a real authentication factor");
    }

    private static String normalizeInvoiceAnswer(String answer) {
        if (answer == null || answer.isBlank() || answer.length() > 32) return null;
        try {
            BigDecimal parsed = new BigDecimal(answer.trim());
            return parsed.setScale(2).toPlainString();
        } catch (NumberFormatException | ArithmeticException e) {
            return null;
        }
    }

    private static String invoiceSignaturePayload(UUID orderId, StepUpChallengeEntity challenge, String answer) {
        String binding = challenge.getInvoiceCurrency() + ":" + challenge.getInvoiceOrderAmount()
                + ":" + challenge.getInvoiceAmount();
        return orderId + ":" + INVOICE_DISCREPANCY + ":" + binding + ":" + answer;
    }
}
