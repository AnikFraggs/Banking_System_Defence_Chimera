package com.chimera.bank.config;

import com.chimera.bank.auth.AuthService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Bridges the local bearer-token sessions into Spring's SecurityContext so that
 * method-level {@code @PreAuthorize} rules evaluate the authenticated principal
 * and role instead of an anonymous token. Requests without a valid token are
 * left anonymous; denial is still enforced by {@code @PreAuthorize} and the
 * service layer. Instantiated directly in the security chain (not a servlet
 * bean) so it is registered exactly once.
 */
public class SessionAuthenticationFilter extends OncePerRequestFilter {

    private final AuthService auth;

    public SessionAuthenticationFilter(AuthService auth) {
        this.auth = auth;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if (SecurityContextHolder.getContext().getAuthentication() == null) {
            auth.resolve(request.getHeader("Authorization")).ifPresent(principal -> {
                var authorities = List.of(new SimpleGrantedAuthority("ROLE_" + principal.role().name()));
                var authentication = new UsernamePasswordAuthenticationToken(principal, null, authorities);
                authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                SecurityContextHolder.getContext().setAuthentication(authentication);
            });
        }
        chain.doFilter(request, response);
    }
}