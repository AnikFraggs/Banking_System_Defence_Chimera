package com.chimera.bank;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * CHIMERA Bank Platform entry point.
 *
 * <p>Scans {@code com.chimera.bank} so the defense-pipeline layers (in the
 * sibling module) are auto-discovered as Spring beans and assembled into the
 * ordered {@code DefensePipeline}.
 */
@SpringBootApplication(scanBasePackages = "com.chimera.bank")
public class PlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlatformApplication.class, args);
    }
}
