package com.chimera.bank.banking;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/banking")
@PreAuthorize("hasRole('CUSTOMER')")
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
            HttpServletRequest request) {
        return bank.overview(auth.require(authorization));
    }

    @PostMapping("/deposit")
    public BankService.AccountOverview deposit(@RequestHeader(value = "Authorization", required = false) String authorization,
                                               @Valid @RequestBody CashRequest body,
                                               HttpServletRequest request) {
        return bank.deposit(auth.requireOneOf(authorization, Role.CUSTOMER), body.amount(), body.reference(),
                resolveClientIp(request));
    }

    @PostMapping("/withdraw")
    public BankService.AccountOverview withdraw(@RequestHeader(value = "Authorization", required = false) String authorization,
                                                @Valid @RequestBody CashRequest body,
                                                HttpServletRequest request) {
        return bank.withdraw(auth.requireOneOf(authorization, Role.CUSTOMER), body.amount(), body.reference(),
                resolveClientIp(request));
    }

    @GetMapping("/mutual-funds")
    public List<BankService.MutualFund> mutualFunds(@RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.require(authorization);
        return bank.mutualFunds();
    }

    // --- NEW SECURE TRANSFER ENDPOINTS ---
    @GetMapping("/security-challenge")
    public BankService.ChallengePrompt getSecurityChallenge(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        return bank.getSecurityChallenge(auth.requireOneOf(authorization, Role.CUSTOMER));
    }

    @PostMapping("/secure-transfer/validate")
    public BankService.SecureTransferResponse validateSecureTransfer(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody Map<String, String> payload,
            HttpServletRequest request) {

        return bank.validateSecureTransfer(
            auth.requireOneOf(authorization, Role.CUSTOMER),
            payload.get("answer"),
            payload.get("beneficiary"),
            new BigDecimal(payload.get("amount")),
            resolveClientIp(request)
        );
    }

    @PostMapping("/secure-transfer/execute")
    public BankService.AccountOverview executeSecureTransfer(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody Map<String, String> payload,
            HttpServletRequest request) {

        return bank.transfer(
            auth.requireOneOf(authorization, Role.CUSTOMER),
            new BigDecimal(payload.get("amount")),
            payload.get("beneficiary"),
            "Secure Transfer",
            resolveClientIp(request)
        );
    }

    private static String resolveClientIp(HttpServletRequest request) {
        String xff = request.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            String first = xff.split(",")[0].trim();
            if (!first.isBlank() && !"unknown".equalsIgnoreCase(first)) {
                return first;
            }
        }
        String xri = request.getHeader("X-Real-IP");
        if (xri != null && !xri.isBlank() && !"unknown".equalsIgnoreCase(xri)) {
            return xri;
        }
        return request.getRemoteAddr();
    }
}