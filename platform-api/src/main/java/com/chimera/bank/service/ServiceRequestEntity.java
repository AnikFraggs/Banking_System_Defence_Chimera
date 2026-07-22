package com.chimera.bank.service;

import jakarta.persistence.*;
import java.time.Instant;

/**
 * A money-movement action a client (account holder) is not permitted to execute
 * directly. Invest / buy / deposit / loan requests are staged here as PENDING
 * and must be approved by an ACCOUNTANT before the ledger is touched.
 */
@Entity
@Table(name = "service_requests")
public class ServiceRequestEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String username;        // requesting client username
    private String customerName;
    private String type;            // DEPOSIT, INVEST, BUY, LOAN
    private double amount;
    @Column(length = 1000)
    private String detail;
    private String paymentMethod;   // NETBANKING, CREDIT_CARD, DEBIT_CARD, RAZORPAY, GPAY
    private String paymentReference;
    private String status;          // PENDING, APPROVED, REJECTED
    private Instant createdAt;
    private String decidedBy;
    private String decisionNote;
    private Instant decidedAt;

    public Long getId() { return id; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getCustomerName() { return customerName; }
    public void setCustomerName(String customerName) { this.customerName = customerName; }
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public double getAmount() { return amount; }
    public void setAmount(double amount) { this.amount = amount; }
    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
    public String getPaymentMethod() { return paymentMethod; }
    public void setPaymentMethod(String paymentMethod) { this.paymentMethod = paymentMethod; }
    public String getPaymentReference() { return paymentReference; }
    public void setPaymentReference(String paymentReference) { this.paymentReference = paymentReference; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public String getDecidedBy() { return decidedBy; }
    public void setDecidedBy(String decidedBy) { this.decidedBy = decidedBy; }
    public String getDecisionNote() { return decisionNote; }
    public void setDecisionNote(String decisionNote) { this.decisionNote = decisionNote; }
    public Instant getDecidedAt() { return decidedAt; }
    public void setDecidedAt(Instant decidedAt) { this.decidedAt = decidedAt; }
}
