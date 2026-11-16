package com.chimera.bank.fraud;

/** A single configured fraud-gate transport; implementations never fall back to one another. */
public interface FraudGateTransport {
    ScoreResponse score(ScoreRequest request);
}
