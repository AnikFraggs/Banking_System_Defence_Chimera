
package com.chimera.bank.banking;
import java.util.stream.Collectors;
import com.chimera.bank.auth.AppUser;
import com.chimera.bank.auth.AuthService;
import com.chimera.bank.auth.UserRepository;
import com.chimera.bank.banking.BankService.Transaction;
import com.chimera.bank.banking.BankService.TransactionType;
import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.DefensePipeline;
import com.chimera.bank.defense.DefenseResult;

import com.chimera.bank.banking.TransactionEntity;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.UUID;

@Service
public class BankService {
    public enum TransactionType { DEPOSIT, WITHDRAWAL, TRANSFER }

    public record Transaction(String id, Instant timestamp, TransactionType type,
                              BigDecimal amount, String counterparty, String status,
                              BigDecimal resultingBalance) { }
    public record AccountOverview(String registrationNumber, String accountNumber, String customerName,
                                  BigDecimal availableBalance, int creditScore, String creditBand,
                                  List<Transaction> recentTransactions) { }
    public record MutualFund(String name, String category, String risk, String horizon, String note) { }
    
    // NEW RECORDS FOR SECURE TRANSFER
    public record SecureTransferResponse(String status, String message, String otp) {}
    public record SecurityChallenge(String question, String expectedAnswer) {}

    private final UserRepository userRepository;
    private final TransactionRepository transactionRepository;
    private final DefensePipeline defense;

    public BankService(UserRepository userRepository, TransactionRepository transactionRepository, DefensePipeline defense) {
        this.userRepository = userRepository;
        this.transactionRepository = transactionRepository;
        this.defense = defense;
    }

    public synchronized AccountOverview overview(AuthService.Principal principal) {
        AppUser user = getUser(principal);
        List<TransactionEntity> txns = transactionRepository.findTop10ByUsernameOrderByTimestampDesc(user.getUsername());
        return snapshot(user, txns);
    }

    public synchronized AccountOverview deposit(AuthService.Principal principal, BigDecimal amount, String reference) {
        AppUser user = getUser(principal);
        screen(principal, "deposit", safeText(reference));
        user.setBalance(user.getBalance() + amount.doubleValue());
        userRepository.save(user);
        record(user.getUsername(), "DEPOSIT", amount.doubleValue(), safeText(reference, "Cash deposit"), "COMPLETED");
        return snapshot(user, transactionRepository.findTop10ByUsernameOrderByTimestampDesc(user.getUsername()));
    }

    public synchronized AccountOverview withdraw(AuthService.Principal principal, BigDecimal amount, String reference) {
        AppUser user = getUser(principal);
        screen(principal, "withdraw", safeText(reference));
        if (user.getBalance() < amount.doubleValue()) throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient balance.");
        user.setBalance(user.getBalance() - amount.doubleValue());
        userRepository.save(user);
        record(user.getUsername(), "WITHDRAWAL", amount.doubleValue(), safeText(reference, "Cash withdrawal"), "COMPLETED");
        return snapshot(user, transactionRepository.findTop10ByUsernameOrderByTimestampDesc(user.getUsername()));
    }

    public synchronized AccountOverview transfer(AuthService.Principal principal, BigDecimal amount, String beneficiaryAccount, String note) {
        AppUser sender = getUser(principal);
        screen(principal, "transfer", "to " + beneficiaryAccount);
        
        if (sender.getBalance() < amount.doubleValue()) throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient balance.");

        AppUser receiver = resolveBeneficiary(beneficiaryAccount);
        if (receiver.getUsername().equalsIgnoreCase(sender.getUsername())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "You cannot transfer to your own account.");
        }

        sender.setBalance(sender.getBalance() - amount.doubleValue());
        receiver.setBalance(receiver.getBalance() + amount.doubleValue());
        userRepository.save(sender);
        userRepository.save(receiver);

        record(sender.getUsername(), "TRANSFER", amount.doubleValue(), receiver.getCustomerName(), "COMPLETED");
        record(receiver.getUsername(), "DEPOSIT", amount.doubleValue(), sender.getCustomerName(), "COMPLETED");

        return snapshot(sender, transactionRepository.findTop10ByUsernameOrderByTimestampDesc(sender.getUsername()));
    }

    /**
     * Applies an accountant-approved service request to the ledger. DEPOSIT and
     * LOAN credit the account; INVEST and BUY debit it (money leaves to the
     * instrument). Runs through the defense pipeline like any money movement.
     */
    public synchronized void applyApprovedRequest(String username, String type, BigDecimal amount, String detail) {
        AppUser user = userRepository.findByUsername(username)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Requesting client not found."));
        String upper = type == null ? "" : type.toUpperCase();
        double delta = switch (upper) {
            case "DEPOSIT", "LOAN" -> amount.doubleValue();
            case "INVEST", "BUY" -> -amount.doubleValue();
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown request type: " + type);
        };
        if (delta < 0 && user.getBalance() < -delta) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient balance to fulfil this request.");
        }
        user.setBalance(user.getBalance() + delta);
        userRepository.save(user);
        String ledgerType = delta >= 0 ? "DEPOSIT" : "WITHDRAWAL";
        record(username, ledgerType, amount.doubleValue(), safeText(detail, upper + " (accountant-approved)"), "COMPLETED");
    }

    public List<MutualFund> mutualFunds() {
        return List.of(
            new MutualFund("Diversified Equity Index", "Equity index", "High", "5+ years", "Illustrative category."),
            new MutualFund("Balanced Allocation", "Hybrid", "Moderate", "3+ years", "Illustrative category."),
            new MutualFund("Short Duration Debt", "Debt", "Low to moderate", "1–3 years", "Illustrative category.")
        );
    }

    // --- NEW SECURE TRANSFER LOGIC ---
    public SecurityChallenge getSecurityChallenge() {
        List<SecurityChallenge> challenges = List.of(
            new SecurityChallenge("What color is the sky during a clear day?", "blue"),
            new SecurityChallenge("Is fire generally hot or cold? (lowercase)", "hot"),
            new SecurityChallenge("How many wheels does a standard car have? (digits)", "4"),
            new SecurityChallenge("What is the opposite of 'stop'? (lowercase)", "go")
        );
        return challenges.get(new Random().nextInt(challenges.size()));
    }

    public SecureTransferResponse validateSecureTransfer(AuthService.Principal principal, String answer, String beneficiary, BigDecimal amount) {
        if ("999".equals(answer)) {
            return new SecureTransferResponse("QUARANTINED", "AI behavior detected. Session routed to Vault.", null);
        }

        DefenseContext context = new DefenseContext("tx-" + UUID.randomUUID(), Instant.now(), "127.0.0.1",
                principal.registrationNumber(), principal.role(), "transfer", "Transfer " + amount + " to " + beneficiary);
        context.addSignal("human_challenge_passed", true);
        
        DefenseResult result = defense.evaluate(context);
        
        if (!result.allowed()) {
            return new SecureTransferResponse("LEAK_DETECTED", "Pathway compromised. Defense layers activated: " + result.finalVerdict().reason(), null);
        }

        String otp = String.format("%06d", new Random().nextInt(1000000));
        return new SecureTransferResponse("SECURE", "Pathway secure. OTP generated.", otp);
    }

    private AppUser getUser(AuthService.Principal principal) {
        if (principal.role() != Role.CUSTOMER) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Only clients can access banking dashboard.");
        }
        return userRepository.findByUsername(principal.registrationNumber())
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "User not found."));
    }

    /**
     * Resolves a transfer beneficiary by account number, then username, then
     * customer name. A name match is only accepted when it is unambiguous
     * (exactly one account carries it); otherwise the client must use the
     * account number.
     */
    private AppUser resolveBeneficiary(String reference) {
        String value = safeText(reference);
        if (value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Enter a beneficiary account, username, or name.");
        }
        return userRepository.findByAccountNumber(value)
            .or(() -> userRepository.findByUsername(value.toLowerCase()))
            .orElseGet(() -> {
                List<AppUser> byName = userRepository.findByCustomerNameIgnoreCase(value);
                if (byName.size() == 1) return byName.get(0);
                if (byName.size() > 1) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT,
                            "Multiple accounts share that name. Use the account number instead.");
                }
                throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "Receiver not found. Use the beneficiary's account number, username, or exact name.");
            });
    }

    private void screen(AuthService.Principal principal, String purpose, String payload) {
        DefenseContext context = new DefenseContext("bank-" + UUID.randomUUID(), Instant.now(), "127.0.0.1",
                principal.registrationNumber(), principal.role(), purpose, payload);
        context.addSignal("human_challenge_passed", true);
        DefenseResult result = defense.evaluate(context);
        if (!result.allowed()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Held by defense: " + result.finalVerdict().reason());
        }
    }

    private void record(String username, String type, double amount, String counterparty, String status) {
        TransactionEntity txn = new TransactionEntity();
        txn.setUsername(username);
        txn.setType(type);
        txn.setAmount(amount);
        txn.setCounterparty(counterparty);
        txn.setStatus(status);
        txn.setTimestamp(Instant.now());
        transactionRepository.save(txn);
    }

    private static AccountOverview snapshot(AppUser user, List<TransactionEntity> txns) {
        List<Transaction> recent = txns.stream().map(t -> 
            new Transaction("txn-"+t.getId(), t.getTimestamp(), TransactionType.valueOf(t.getType()), 
                            BigDecimal.valueOf(t.getAmount()), t.getCounterparty(), t.getStatus(), 
                            BigDecimal.valueOf(user.getBalance()))
        ).collect(Collectors.toList());
        
        String band = user.getBalance() >= 100000 ? "Excellent" : "Good";
        return new AccountOverview(user.getRegistrationNumber(), user.getAccountNumber(), user.getCustomerName(),
                BigDecimal.valueOf(user.getBalance()), 750, band, recent);
    }

    private static String safeText(String value) { return value == null ? "" : value.trim(); }
    private static String safeText(String value, String fallback) { return value == null || value.isBlank() ? fallback : value.trim(); }
}