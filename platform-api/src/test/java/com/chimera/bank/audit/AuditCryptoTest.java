package com.chimera.bank.audit;

import org.junit.jupiter.api.Test;

import java.util.Base64;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AuditCryptoTest {

    private final AuditCrypto crypto = new AuditCrypto("unit-test-key", "test");

    @Test
    void roundTripsWithFreshIvEachTime() {
        String a = crypto.encryptAesGcm("{\"k\":\"v\"}");
        String b = crypto.encryptAesGcm("{\"k\":\"v\"}");

        assertNotEquals(a, b);
        assertEquals("{\"k\":\"v\"}", crypto.decryptAesGcm(a));
        assertEquals("{\"k\":\"v\"}", crypto.decryptAesGcm(b));
    }

    @Test
    void rejectsTamperedCiphertext() {
        byte[] raw = Base64.getDecoder().decode(crypto.encryptAesGcm("secret"));
        raw[raw.length - 1] ^= 1;

        assertThrows(IllegalStateException.class,
                () -> crypto.decryptAesGcm(Base64.getEncoder().encodeToString(raw)));
    }

    @Test
    void rejectsOtherKey() {
        String sealed = crypto.encryptAesGcm("secret");

        assertThrows(IllegalStateException.class,
                () -> new AuditCrypto("another-key", "test").decryptAesGcm(sealed));
    }
}
