package com.chimera.bank.auth;

import com.chimera.bank.common.rbac.Role;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.test.context.support.WithSecurityContextFactory;

import java.time.Instant;
import java.util.List;

public class WithMockChimeraUserSecurityContextFactory implements WithSecurityContextFactory<WithMockChimeraUser> {
    @Override
    public SecurityContext createSecurityContext(WithMockChimeraUser annotation) {
        SecurityContext context = SecurityContextHolder.createEmptyContext();
        Role role = Role.valueOf(annotation.role());
        AuthService.Principal principal = new AuthService.Principal(
                annotation.username(),
                annotation.displayName(),
                role,
                Instant.now().plusSeconds(3600)
        );
        UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(
                principal,
                "password",
                List.of(new SimpleGrantedAuthority("ROLE_" + role.name()))
        );
        context.setAuthentication(auth);
        return context;
    }
}
