package com.chimera.bank.evaluation;

import com.chimera.bank.auth.AuthService;
import com.chimera.bank.common.rbac.Role;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/** Manager-only, local dataset validation surface. */
@RestController
@RequestMapping("/api/evaluation")
public class EvaluationController {
    private final AuthService auth;
    private final DatasetValidationService validation;
    private final ThreatSimulationService simulationService; // NEW: Inject simulation service

    public EvaluationController(AuthService auth, DatasetValidationService validation, ThreatSimulationService simulationService) {
        this.auth = auth;
        this.validation = validation;
        this.simulationService = simulationService;
    }

    @GetMapping("/datasets")
    public List<DatasetValidationService.DatasetInfo> datasets(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return validation.list();
    }

    @PostMapping(value = "/datasets", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public DatasetValidationService.DatasetInfo upload(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("file") MultipartFile file) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return validation.upload(file);
    }

    @PostMapping("/run")
    public DatasetValidationService.RunResult run(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @org.springframework.web.bind.annotation.RequestBody DatasetValidationService.RunRequest request) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return validation.run(request);
    }

    @PostMapping("/safety-pack")
    public DatasetValidationService.SafetyPackResult safetyPack(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return validation.runSafetyPack();
    }

    @GetMapping("/latest")
    public DatasetValidationService.RunResult latest(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return validation.latest();
    }

    // NEW: Live Threat Simulation Endpoint
    @PostMapping("/simulate")
    public ThreatSimulationService.SimulationResult simulate(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @org.springframework.web.bind.annotation.RequestBody ThreatSimulationService.SimulationRequest request) {
        auth.requireOneOf(authorization, Role.MANAGER);
        return simulationService.runAttackSimulation(request.getAttackType());
    }
}