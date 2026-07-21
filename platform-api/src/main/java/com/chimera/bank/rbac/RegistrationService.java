package com.chimera.bank.rbac;

import com.chimera.bank.common.rbac.AccessNode;
import com.chimera.bank.common.rbac.Role;
import org.springframework.stereotype.Service;

import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registers users into the access tree and records the reg.no + originating IP
 * captured at sign-up. The registration IP is stored only as a one-way hash so
 * it can be correlated for history checks without retaining the raw address.
 *
 * <p>A single MANAGER root anchors the tree in this reference build; production
 * would load the org tree from an identity provider.
 */
@Service
public class RegistrationService {

    private final AccessNode root = new AccessNode("MGR-ROOT", Role.MANAGER, "HQ");
    private final ConcurrentHashMap<String, String> registrationIpHash = new ConcurrentHashMap<>();

    public RegistrationService() {
        // Seed a small tree so the platform is usable out of the box.
        AccessNode acct = root.addChild(new AccessNode("ACC-001", Role.ACCOUNTANT, "BR-DEL-01"));
        acct.addChild(new AccessNode("CUST-1001", Role.CUSTOMER, "BR-DEL-01"));
        acct.addChild(new AccessNode("CUST-1002", Role.CUSTOMER, "BR-DEL-01"));
    }

    public AccessNode register(String regNo, Role role, String branchCode,
                               String parentRegNo, String sourceIp) {
        AccessNode parent = root.findByRegNo(parentRegNo)
                .orElseThrow(() -> new IllegalArgumentException("Unknown parent reg.no: " + parentRegNo));
        AccessNode node = parent.addChild(new AccessNode(regNo, role, branchCode));
        registrationIpHash.put(regNo, hash(sourceIp));
        return node;
    }

    public Optional<AccessNode> find(String regNo) {
        return root.findByRegNo(regNo);
    }

    public AccessNode root() {
        return root;
    }

    /** True if the caller node may act on the target node (clearance + subtree). */
    public boolean mayActOn(String callerRegNo, String targetRegNo) {
        Optional<AccessNode> caller = find(callerRegNo);
        Optional<AccessNode> target = find(targetRegNo);
        return caller.isPresent() && target.isPresent() && caller.get().mayActOn(target.get());
    }

    /** True when the presented IP matches the hash captured at registration. */
    public boolean ipMatchesRegistration(String regNo, String sourceIp) {
        String stored = registrationIpHash.get(regNo);
        return stored != null && stored.equals(hash(sourceIp));
    }

    private static String hash(String value) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
            return "sha256:" + HexFormat.of().formatHex(digest).substring(0, 16);
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
