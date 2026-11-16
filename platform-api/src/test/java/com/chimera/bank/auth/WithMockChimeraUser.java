package com.chimera.bank.auth;

import org.springframework.security.test.context.support.WithSecurityContext;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

@Retention(RetentionPolicy.RUNTIME)
@WithSecurityContext(factory = WithMockChimeraUserSecurityContextFactory.class)
public @interface WithMockChimeraUser {
    String username() default "testuser";
    String displayName() default "Test User";
    String role() default "CUSTOMER";
}
