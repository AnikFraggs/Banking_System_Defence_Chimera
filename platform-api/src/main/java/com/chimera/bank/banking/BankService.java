package com.chimera.bank.banking;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.defense.DefenseContext;
import com.chimera.bank.common.rbac.Role;
import com.chimera.bank.defense.DefensePipeline;
import com.chimera.bank.defense.DefenseResult;
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
import java.util.Random;
import java.util.Map;
import java.util.UUID;

/**
 * In-memory, non-production banking ledger used to demonstrate the frontend and
 * authorization flows. It intentionally has no payment-network integration and
 * resets when the API restarts. Do not use it to hold real funds or PII.
 */
@Service
public class BankService {
    public enum TransactionType { DEPOSIT, WITHDRAWAL, TRANSFER }

    public record Transaction(String id, Instant timestamp, TransactionType type,
                              BigDecimal amount, String counterparty, String status,
                              BigDecimal resultingBalance) { }
    public record AccountOverview(String registrationNumber, String accountNumber, String customerName,
                                  BigDecimal availableBalance, int creditScore, String creditBand,
                                  List<Transaction> recentTransactions) { }
    public record MutualFund(String name, String category, String risk, String horizon,
                             String note) { }

    private static final class Account {
        private final String registrationNumber;
        private final String accountNumber;
        private final String customerName;
        private final String email;
        private final int creditScore;
        private BigDecimal balance;
        private final List<Transaction> transactions = new ArrayList<>();

        private Account(String registrationNumber, String accountNumber, String customerName,String email,
                        BigDecimal balance, int creditScore) {
            this.registrationNumber = registrationNumber;
            this.accountNumber = accountNumber;
            this.customerName = customerName;
            this.email=email;
            this.balance = money(balance);
            this.creditScore = creditScore;
        }
    }

    private final Map<String, Account> accounts = new LinkedHashMap<>();
    private final DefensePipeline defense;

    public BankService(DefensePipeline defense) {
        this.defense = defense;
        Account anita = new Account("CUST-1001", "CHM-1024-1189", "Anita Rao", "anita.rao@chimera.bank",new BigDecimal("256400.00"), 778);
        Account rohan = new Account("CUST-1002", "CHM-1024-1190", "Rohan Kapoor", "rohan.kapoor@chimera.bank",new BigDecimal("87500.00"), 716);
        accounts.put(anita.registrationNumber, anita);
        accounts.put(rohan.registrationNumber, rohan);
        addSeed(anita, TransactionType.DEPOSIT, new BigDecimal("25000"), "Salary credit", "COMPLETED");
        addSeed(anita, TransactionType.TRANSFER, new BigDecimal("4200"), "Rent payment", "COMPLETED");
        addSeed(rohan, TransactionType.DEPOSIT, new BigDecimal("5000"), "Opening balance", "COMPLETED");
    }

    public synchronized AccountOverview overview(AuthService.Principal principal, String requestedRegistrationNumber) {
        Account account = accountForViewer(principal, requestedRegistrationNumber);
        return snapshot(account);
    }
    public synchronized AccountOverview executeSecureTransfer(AuthService.Principal principal, BigDecimal amount, String beneficiary, String method) {
        Account sender = requireOwnCustomerAccount(principal);
        BigDecimal value = positive(amount);
        
        if (sender.balance.compareTo(value) < 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient available balance.");
        }

        // Simulate Email for > 2 Lakhs
        String note = "Transfer via " + method;
        if (value.compareTo(new BigDecimal("200000")) > 0) {
            note += " (Email confirmation sent to " + sender.email + ")";
        }

        sender.balance = sender.balance.subtract(value);
        record(sender, TransactionType.TRANSFER, value, beneficiary, "COMPLETED");
        return snapshot(sender);
    }
    public synchronized List<Transaction> transactions(AuthService.Principal principal, String requestedRegistrationNumber) {
        Account account = accountForViewer(principal, requestedRegistrationNumber);
        return account.transactions.stream().sorted(Comparator.comparing(Transaction::timestamp).reversed()).toList();
    }

    public synchronized AccountOverview deposit(AuthService.Principal principal, BigDecimal amount, String reference) {
        Account account = requireOwnCustomerAccount(principal);
        screen(principal, "deposit", safeText(reference));
        BigDecimal value = positive(amount);
        account.balance = account.balance.add(value);
        record(account, TransactionType.DEPOSIT, value, blankToDefault(reference, "Cash deposit"), "COMPLETED");
        return snapshot(account);
    }

    public synchronized AccountOverview withdraw(AuthService.Principal principal, BigDecimal amount, String reference) {
        Account account = requireOwnCustomerAccount(principal);
        screen(principal, "withdraw", safeText(reference));
        BigDecimal value = positive(amount);
        if (account.balance.compareTo(value) < 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient available balance.");
        }
        account.balance = account.balance.subtract(value);
        record(account, TransactionType.WITHDRAWAL, value, blankToDefault(reference, "Cash withdrawal"), "COMPLETED");
        return snapshot(account);
    }

    public synchronized AccountOverview transfer(AuthService.Principal principal, BigDecimal amount, String beneficiary,
                                                 String note) {
        Account sender = requireOwnCustomerAccount(principal);
        String cleanBeneficiary = requireText(beneficiary, "Beneficiary is required.");
        screen(principal, "transfer", "beneficiary=" + cleanBeneficiary + "; note=" + safeText(note));
        BigDecimal value = positive(amount);
        if (sender.balance.compareTo(value) < 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient available balance.");
        }
        sender.balance = sender.balance.subtract(value);
        record(sender, TransactionType.TRANSFER, value, cleanBeneficiary, "COMPLETED");
        return snapshot(sender);
    }

    public List<MutualFund> mutualFunds() {
        return List.of(
                new MutualFund("Diversified Equity Index", "Equity index", "High", "5+ years",
                        "Illustrative category only; not a recommendation."),
                new MutualFund("Balanced Allocation", "Hybrid", "Moderate", "3+ years",
                        "Illustrative category only; review scheme documents and fees."),
                new MutualFund("Short Duration Debt", "Debt", "Low to moderate", "1–3 years",
                        "Illustrative category only; interest-rate and credit risk still apply."));
    }
    public record SecurityChallenge(String question, String expectedAnswer) { }

    public SecurityChallenge getSecurityChallenge() {
        List<SecurityChallenge> challenges = List.of(
            new SecurityChallenge("What color is the sky during a clear day?", "blue"),
            new SecurityChallenge("Is fire generally hot or cold? (lowercase)", "hot"),
            new SecurityChallenge("How many wheels does a standard car have? (digits)", "4"),
            new SecurityChallenge("What is the opposite of 'stop'? (lowercase)", "go")
        );
        return challenges.get(new Random().nextInt(challenges.size()));
    }

    private Account accountForViewer(AuthService.Principal principal, String requestedRegistrationNumber) {
        String target = requestedRegistrationNumber == null || requestedRegistrationNumber.isBlank()
                ? (principal.role() == Role.CUSTOMER ? principal.registrationNumber() : "CUST-1001") : requestedRegistrationNumber;
        if (principal.role() == Role.CUSTOMER && !principal.registrationNumber().equals(target)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Clients can view only their own account.");
        }
        return requireAccount(target);
    }

    private Account requireOwnCustomerAccount(AuthService.Principal principal) {
        if (principal.role() != Role.CUSTOMER) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "Only a signed-in client can initiate this demo money movement.");
        }
        return requireAccount(principal.registrationNumber());
    }

    private Account requireAccount(String registrationNumber) {
        Account account = accounts.get(registrationNumber);
        if (account == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "No customer account exists for " + registrationNumber + ".");
        }
        return account;
    }

    private void screen(AuthService.Principal principal, String purpose, String payload) {
        DefenseContext context = new DefenseContext("bank-" + UUID.randomUUID(), Instant.now(), "127.0.0.1",
                principal.registrationNumber(), principal.role(), purpose, payload);
        context.addSignal("human_challenge_passed", true);
        DefenseResult result = defense.evaluate(context);
        if (!result.allowed()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Transaction was held by " + result.finalVerdict().layer() + ": " + result.finalVerdict().reason());
        }
    }

    private static AccountOverview snapshot(Account account) {
        List<Transaction> recent = account.transactions.stream()
                .sorted(Comparator.comparing(Transaction::timestamp).reversed()).limit(6).toList();
        String band = account.creditScore >= 750 ? "Excellent" : account.creditScore >= 700 ? "Good" : "Building";
        return new AccountOverview(account.registrationNumber, account.accountNumber, account.customerName,
                money(account.balance), account.creditScore, band, recent);
    }

    private static BigDecimal positive(BigDecimal amount) {
        if (amount == null || amount.signum() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Amount must be greater than zero.");
        }
        return money(amount);
    }

    private static String requireText(String value, String message) {
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
        return value.trim();
    }

    private static String safeText(String value) {
        return value == null ? "" : value.trim();
    }

    private static String blankToDefault(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private static BigDecimal money(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    private static void addSeed(Account account, TransactionType type, BigDecimal amount, String counterparty, String status) {
        account.transactions.add(new Transaction("seed-" + UUID.randomUUID(), Instant.now().minusSeconds(account.transactions.size() * 3600L),
                type, money(amount), counterparty, status, account.balance));
    }

    private static void record(Account account, TransactionType type, BigDecimal amount, String counterparty, String status) {
        account.transactions.add(new Transaction(UUID.randomUUID().toString(), Instant.now(), type,
                money(amount), counterparty, status, money(account.balance)));
    }
        public SecureTransferResponse validateSecureTransfer(AuthService.Principal principal, String answer, String beneficiary, BigDecimal amount) {
        // 1. Check for AI Ghost Trap
        if ("999".equals(answer)) {
            return new SecureTransferResponse("QUARANTINED", "AI behavior detected. Session routed to Vault.", null);
        }

        // 2. Run through your actual DefensePipeline
        DefenseContext context = new DefenseContext("tx-" + UUID.randomUUID(), Instant.now(), "127.0.0.1",
                principal.registrationNumber(), principal.role(), "transfer", "Transfer " + amount + " to " + beneficiary);
        context.addSignal("human_challenge_passed", true);
        
        DefenseResult result = defense.evaluate(context);
        
        // 3. Check if the 6 layers blocked it
        if (!result.allowed()) {
            return new SecureTransferResponse("LEAK_DETECTED", 
                "Pathway compromised. Defense layers activated: " + result.finalVerdict().reason(), null);
        }

        // 4. If secure, generate OTP
        String otp = String.format("%06d", new java.util.Random().nextInt(1000000));
        return new SecureTransferResponse("SECURE", "Pathway secure. OTP generated.", otp);
    }

    // Add this record at the bottom of BankService class
    public record SecureTransferResponse(String status, String message, String otp) { }        
}