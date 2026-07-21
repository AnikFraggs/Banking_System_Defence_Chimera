package com.chimera.bank.banking;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** Banking-demo endpoints, all backed by the local in-memory ledger. */
@RestController
@RequestMapping("/api/banking")
public class BankingController {
    private final AuthService auth;
    private final BankService bank;

    public BankingController(AuthService auth, BankService bank) {
        this.auth = auth;
        this.bank = bank;
    }

    public record CashRequest(@NotNull @DecimalMin(value = "0.01") BigDecimal amount, String reference) { }
    public record TransferRequest(@NotNull @DecimalMin(value = "0.01") BigDecimal amount,
                                  @NotBlank String beneficiary, String note) { }

    @GetMapping("/dashboard")
    public BankService.AccountOverview dashboard(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam(required = false) String registrationNumber) {
        return bank.overview(auth.require(authorization), registrationNumber);
    }

    @GetMapping("/transactions")
    public List<BankService.Transaction> transactions(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam(required = false) String registrationNumber) {
        return bank.transactions(auth.require(authorization), registrationNumber);
    }

    @PostMapping("/deposit")
    public BankService.AccountOverview deposit(@RequestHeader(value = "Authorization", required = false) String authorization,
                                               @Valid @RequestBody CashRequest body) {
        return bank.deposit(auth.requireOneOf(authorization, Role.CUSTOMER), body.amount(), body.reference());
    }

    @PostMapping("/withdraw")
    public BankService.AccountOverview withdraw(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @Valid @RequestBody CashRequest body) {
        return bank.withdraw(auth.requireOneOf(authorization, Role.CUSTOMER), body.amount(), body.reference());
    }

    @PostMapping("/transfer")
    public BankService.AccountOverview transfer(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @Valid @RequestBody TransferRequest body) {
        return bank.transfer(auth.requireOneOf(authorization, Role.CUSTOMER), body.amount(), body.beneficiary(), body.note());
    }

    @GetMapping("/mutual-funds")
    public List<BankService.MutualFund> mutualFunds(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return bank.mutualFunds();
    }
    @PostMapping("/secure-transfer/validate")
    public BankService.SecureTransferResponse validateSecureTransfer(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody Map<String, String> payload) {
        
        BankService.SecureTransferResponse response = bank.validateSecureTransfer(
            auth.requireOneOf(authorization, Role.CUSTOMER),
            payload.get("answer"),
            payload.get("beneficiary"),
            new BigDecimal(payload.get("amount"))
        );
        return response;
    }
    @GetMapping("/security-challenge")
    public BankService.SecurityChallenge getSecurityChallenge(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.CUSTOMER);
        return bank.getSecurityChallenge();
    }
    @PostMapping("/secure-transfer/execute")
    public BankService.AccountOverview executeSecureTransfer(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody Map<String, String> payload) {
        
        return bank.executeSecureTransfer(
            auth.requireOneOf(authorization, Role.CUSTOMER),
            new BigDecimal(payload.get("amount")),
            payload.get("beneficiary"),
            payload.get("method")
        );
    }
}