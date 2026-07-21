package com.chimera.bank.auth;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Local development authentication surface. */
@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final AuthService auth;

    public AuthController(AuthService auth) {
        this.auth = auth;
    }

    public record LoginBody(@NotBlank String username, @NotBlank String password, @NotBlank String role, String authKey) { }

    @PostMapping("/login")
    public ResponseEntity<AuthService.SessionView> login(@Valid @RequestBody LoginBody body) {
        return ResponseEntity.ok(auth.login(new AuthService.LoginRequest(
                body.username(), body.password(), body.role(), body.authKey())));
    }

    @GetMapping("/me")
    public AuthService.Principal me(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return auth.require(authorization);
    }
}