package com.chimera.bank.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Intercepts Bearer tokens and authenticates principals into the Spring SecurityContextHolder.
 * Maps {@link com.chimera.bank.common.rbac.Role} to Spring Security granted authorities (ROLE_CUSTOMER, etc.).
 */
@Component
public class ChimeraAuthFilter extends OncePerRequestFilter {

    private final AuthService authService;

    public ChimeraAuthFilter(AuthService authService) {
        this.authService = authService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String authHeader = request.getHeader("Authorization");
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            try {
                AuthService.Principal principal = authService.require(authHeader);
                if (principal != null) {
                    List<SimpleGrantedAuthority> authorities = List.of(
                            new SimpleGrantedAuthority("ROLE_" + principal.role().name())
                    );
                    UsernamePasswordAuthenticationToken authentication =
                            new UsernamePasswordAuthenticationToken(principal, null, authorities);
                    SecurityContextHolder.getContext().setAuthentication(authentication);
                }
            } catch (Exception ignored) {
                // If token is invalid or expired, leave SecurityContext empty so entry point handles 401
            }
        }
        filterChain.doFilter(request, response);
    }
}
