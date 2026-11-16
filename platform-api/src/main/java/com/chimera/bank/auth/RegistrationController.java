package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/api/auth")
public class RegistrationController {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    @Autowired
    public RegistrationController(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    public record RegistrationRequest(String username, String password, String customerName, String role) {}

    public record RegistrationResponse(String message, String customerName, String accountNumber,
                                       String registrationNumber, String username) {}

    @PostMapping("/register")
    public RegistrationResponse register(@RequestBody RegistrationRequest request) {
        if (userRepository.findByUsername(request.username()).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }

        AppUser user = new AppUser();
        user.setUsername(request.username());
        user.setPassword(passwordEncoder.encode(request.password())); // Hashed in production
        user.setCustomerName(request.customerName());
        // Self-registration is always CUSTOMER; elevated roles require admin provisioning.
        user.setRole(Role.CUSTOMER.name());
        user.setRegistrationNumber("CUST-" + System.currentTimeMillis());
        user.setAccountNumber("CHM-" + (1000000 + (int)(Math.random() * 9000000)));
        user.setBalance(10000.00); // Starting balance for new users

        userRepository.save(user);
        return new RegistrationResponse(
            "Account created successfully for " + request.customerName() + "! Your Account Number is " + user.getAccountNumber(),
            request.customerName(),
            user.getAccountNumber(),
            user.getRegistrationNumber(),
            request.username()
        );
    }
}