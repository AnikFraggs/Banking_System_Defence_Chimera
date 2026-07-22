package com.chimera.bank.service;

import jakarta.persistence.*;
import java.time.Instant;

/**
 * A read-only client's advisory message to a customer / the bank. Clients have
 * no write access to the ledger, but may leave suggestions here.
 */
@Entity
@Table(name = "suggestions")
public class SuggestionEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String authorUsername;
    private String authorName;
    private String toCustomer;
    @Column(length = 2000)
    private String message;
    private Instant createdAt;

    public Long getId() { return id; }
    public String getAuthorUsername() { return authorUsername; }
    public void setAuthorUsername(String authorUsername) { this.authorUsername = authorUsername; }
    public String getAuthorName() { return authorName; }
    public void setAuthorName(String authorName) { this.authorName = authorName; }
    public String getToCustomer() { return toCustomer; }
    public void setToCustomer(String toCustomer) { this.toCustomer = toCustomer; }
    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
