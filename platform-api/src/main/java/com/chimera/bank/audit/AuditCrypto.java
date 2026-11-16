package com.chimera.bank.audit;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

@Component
public class AuditCrypto {
    private static final byte[] VAULT_KEY_INFO =
            "chimera/deception-vault/aes-256-gcm/v1".getBytes(StandardCharsets.UTF_8);
    private static final int GCM_IV_BYTES = 12;
    private static final int GCM_TAG_BITS = 128;

    private final byte[] key;
    private final String keyVersion;
    private final SecretKeySpec vaultKey;
    private final SecureRandom random = new SecureRandom();

    public AuditCrypto(@Value("${chimera.checkout.audit.hmac-key:${AUDIT_HMAC_KEY:}}") String configuredKey,
                       @Value("${chimera.checkout.audit.key-version:local-v1}") String keyVersion) {
        if (configuredKey == null || configuredKey.isBlank()) {
            this.key = new byte[32];
            new SecureRandom().nextBytes(this.key);
            this.keyVersion = "ephemeral-" + keyVersion;
        } else {
            this.key = configuredKey.getBytes(StandardCharsets.UTF_8);
            this.keyVersion = keyVersion;
        }
        // HKDF keeps the vault key independent of hmac(): hmac() outputs never reveal it.
        this.vaultKey = new SecretKeySpec(hkdfSha256(this.key, VAULT_KEY_INFO), "AES");
    }

    public String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    public String hmac(String value) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return HexFormat.of().formatHex(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("HMAC-SHA256 is unavailable", e);
        }
    }

    public boolean validSignature(String value, String signature) {
        return MessageDigest.isEqual(hmac(value).getBytes(StandardCharsets.UTF_8),
                signature.getBytes(StandardCharsets.UTF_8));
    }

    public String keyVersion() {
        return keyVersion;
    }

    /** AES-256-GCM, random 96-bit IV; returns Base64(iv || ciphertext || tag). */
    public String encryptAesGcm(String plaintext) {
        try {
            byte[] iv = new byte[GCM_IV_BYTES];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, vaultKey, new GCMParameterSpec(GCM_TAG_BITS, iv));
            byte[] sealed = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            byte[] out = new byte[GCM_IV_BYTES + sealed.length];
            System.arraycopy(iv, 0, out, 0, GCM_IV_BYTES);
            System.arraycopy(sealed, 0, out, GCM_IV_BYTES, sealed.length);
            return Base64.getEncoder().encodeToString(out);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("AES-256-GCM encryption failed", e);
        }
    }

    /** Inverse of {@link #encryptAesGcm}; throws if the key is wrong or the data was altered. */
    public String decryptAesGcm(String envelope) {
        byte[] in = Base64.getDecoder().decode(envelope);
        if (in.length < GCM_IV_BYTES + GCM_TAG_BITS / 8) {
            throw new IllegalArgumentException("AES-GCM envelope too short");
        }
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, vaultKey, new GCMParameterSpec(GCM_TAG_BITS, in, 0, GCM_IV_BYTES));
            return new String(cipher.doFinal(in, GCM_IV_BYTES, in.length - GCM_IV_BYTES), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("AES-256-GCM decryption failed (wrong key or tampered data)", e);
        }
    }

    private static byte[] hkdfSha256(byte[] ikm, byte[] info) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(new byte[32], "HmacSHA256"));
            byte[] prk = mac.doFinal(ikm);
            mac.init(new SecretKeySpec(prk, "HmacSHA256"));
            mac.update(info);
            mac.update((byte) 1);
            return mac.doFinal();
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("HKDF-SHA256 is unavailable", e);
        }
    }
}
