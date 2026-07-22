package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/auth")
public class RegistrationController {

    private final UserRepository userRepository;

    public RegistrationController(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public record RegistrationRequest(String username, String password, String customerName, String role) {}

    @PostMapping("/register")
    public String register(@RequestBody RegistrationRequest request) {
        if (userRepository.findByUsername(request.username()).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }

        AppUser user = new AppUser();
        user.setUsername(request.username());
        user.setPassword(request.password()); // In production, hash this!
        user.setCustomerName(request.customerName());
        user.setRole(request.role() == null ? Role.CUSTOMER.name() : request.role());
        user.setRegistrationNumber("CUST-" + System.currentTimeMillis());
        user.setAccountNumber("CHM-" + (1000000 + (int)(Math.random() * 9000000)));
        user.setBalance(10000.00); // Starting balance for new users

        userRepository.save(user);
        return "Account created successfully for " + request.customerName() + "! Your Account Number is " + user.getAccountNumber();
    }
}