package com.chimera.bank.service;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.banking.BankService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Set;

/**
 * Interconnects the client-facing request surface with accountant approval.
 * A client (account holder) cannot invest, buy, take a loan, or deposit
 * directly — they raise a request that an accountant must approve. Approval is
 * the only path that touches the ledger, keeping money movement gated behind a
 * second human role.
 */
@Service
public class ServiceRequestService {

    private static final Set<String> VALID_TYPES = Set.of("DEPOSIT", "INVEST", "BUY", "LOAN");

    private final ServiceRequestRepository requests;
    private final BankService bank;

    public ServiceRequestService(ServiceRequestRepository requests, BankService bank) {
        this.requests = requests;
        this.bank = bank;
    }

    public ServiceRequestEntity create(AuthService.Principal client, String type, BigDecimal amount,
                                       String detail, String paymentMethod, String paymentReference) {
        String upper = type == null ? "" : type.trim().toUpperCase();
        if (!VALID_TYPES.contains(upper)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Request type must be one of DEPOSIT, INVEST, BUY, LOAN.");
        }
        if (amount == null || amount.signum() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Amount must be positive.");
        }
        ServiceRequestEntity request = new ServiceRequestEntity();
        request.setUsername(client.registrationNumber());
        request.setCustomerName(client.displayName());
        request.setType(upper);
        request.setAmount(amount.doubleValue());
        request.setDetail(detail == null ? "" : detail.trim());
        request.setPaymentMethod(paymentMethod);
        request.setPaymentReference(paymentReference);
        request.setStatus("PENDING");
        request.setCreatedAt(Instant.now());
        return requests.save(request);
    }

    public List<ServiceRequestEntity> forClient(AuthService.Principal client) {
        return requests.findByUsernameOrderByCreatedAtDesc(client.registrationNumber());
    }

    public List<ServiceRequestEntity> pending() {
        return requests.findByStatusOrderByCreatedAtDesc("PENDING");
    }

    public List<ServiceRequestEntity> all() {
        return requests.findAllByOrderByCreatedAtDesc();
    }

    public ServiceRequestEntity decide(AuthService.Principal accountant, Long id, boolean approve, String note) {
        ServiceRequestEntity request = requests.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Request not found."));
        if (!"PENDING".equals(request.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Request already " + request.getStatus() + ".");
        }
        if (approve) {
            bank.applyApprovedRequest(request.getUsername(), request.getType(),
                    BigDecimal.valueOf(request.getAmount()), request.getDetail());
            request.setStatus("APPROVED");
        } else {
            request.setStatus("REJECTED");
        }
        request.setDecidedBy(accountant.displayName());
        request.setDecisionNote(note == null ? "" : note.trim());
        request.setDecidedAt(Instant.now());
        return requests.save(request);
    }
}
