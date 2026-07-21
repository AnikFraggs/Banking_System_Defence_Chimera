package com.chimera.bank.evaluation;

import com.chimera.bank.defense.DefenseOrchestrator;
import com.chimera.bank.defense.dataset.CsvDatasetLoader;
import com.chimera.bank.defense.redteam.AdversarialSample;
import com.chimera.bank.defense.redteam.AdversarialSampleGenerator;
import com.chimera.bank.defense.validation.ValidationHarness;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Local, manager-operated CSV ingestion and independent-label validation. */
@Service
public class DatasetValidationService {
    public record DatasetInfo(String filename, long bytes, Instant uploadedAt) { }
    public record RunRequest(String filename, String labelColumn, String maliciousValue, String payloadColumn,
                             String roleColumn, String purposeColumn, String ipColumn, String severityColumn) { }
    public record RunResult(String filename, Instant evaluatedAt, ValidationHarness.ValidationReport report) { }
    public record SafetyPackResult(Instant evaluatedAt, int totalSamples, int seenSamples, int unseenSamples,
                                   RunResult seen, RunResult unseen, RunResult combined) { }

    private final Path datasetRoot;
    private final DefenseOrchestrator orchestrator;
    private volatile RunResult latest;

    public DatasetValidationService(@Value("${chimera.datasets.path}") String datasetPath,
                                    DefenseOrchestrator orchestrator) {
        this.datasetRoot = Path.of(datasetPath).toAbsolutePath().normalize();
        this.orchestrator = orchestrator;
        try {
            Files.createDirectories(datasetRoot);
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot create local dataset directory", e);
        }
    }

    public DatasetInfo upload(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Choose a non-empty CSV file.");
        }
        String supplied = file.getOriginalFilename() == null ? "" : file.getOriginalFilename();
        if (!supplied.toLowerCase().endsWith(".csv")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Only CSV files are accepted.");
        }
        Path destination = resolveFilename(supplied);
        try {
            Files.copy(file.getInputStream(), destination, StandardCopyOption.REPLACE_EXISTING);
            return new DatasetInfo(destination.getFileName().toString(), Files.size(destination), Instant.now());
        } catch (IOException e) {
            throw new UncheckedIOException("Could not store the local dataset", e);
        }
    }

    public List<DatasetInfo> list() {
        try (var paths = Files.list(datasetRoot)) {
            return paths.filter(Files::isRegularFile).filter(path -> path.getFileName().toString().toLowerCase().endsWith(".csv"))
                    .map(path -> {
                        try {
                            return new DatasetInfo(path.getFileName().toString(), Files.size(path), Files.getLastModifiedTime(path).toInstant());
                        } catch (IOException e) {
                            throw new UncheckedIOException(e);
                        }
                    }).toList();
        } catch (IOException e) {
            throw new UncheckedIOException("Could not list local datasets", e);
        }
    }

    public synchronized RunResult run(RunRequest request) {
        if (isBlank(request.filename()) || isBlank(request.labelColumn()) || isBlank(request.payloadColumn())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Filename, label column, and payload column are required.");
        }
        CsvDatasetLoader.ColumnMapping mapping = new CsvDatasetLoader.ColumnMapping(request.labelColumn(), request.maliciousValue(),
                request.payloadColumn(), emptyToNull(request.roleColumn()), emptyToNull(request.purposeColumn()),
                emptyToNull(request.ipColumn()), emptyToNull(request.severityColumn()));
        List<AdversarialSample> samples = CsvDatasetLoader.load(resolveFilename(request.filename()), mapping);
        if (samples.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "The dataset has no data rows.");
        }
        ValidationHarness.ValidationReport report = new ValidationHarness(orchestrator).run(samples);
        latest = new RunResult(resolveFilename(request.filename()).getFileName().toString(), Instant.now(), report);
        return latest;
    }

    /**
     * Runs a deterministic 200-sample local-only safety pack.  Every sample is
     * directed at this application's own defense pipeline; no request leaves
     * the process and no external target is contacted. The 80/20 partition is
     * deterministic so seen and held-out (unseen) reports remain reproducible.
     */
    public synchronized SafetyPackResult runSafetyPack() {
        List<AdversarialSample> selected = new ArrayList<>(AdversarialSampleGenerator.generate().subList(0, 200));
        List<AdversarialSample> seen = new ArrayList<>();
        List<AdversarialSample> unseen = new ArrayList<>();
        for (int i = 0; i < selected.size(); i++) {
            if (i % 5 == 0) {
                unseen.add(selected.get(i));
            } else {
                seen.add(selected.get(i));
            }
        }
        Instant now = Instant.now();
        ValidationHarness harness = new ValidationHarness(orchestrator);
        RunResult seenResult = new RunResult("chimera-security-seen-160", now, harness.run(seen));
        RunResult unseenResult = new RunResult("chimera-security-unseen-40", now, harness.run(unseen));
        RunResult combinedResult = new RunResult("chimera-controlled-safety-pack-200", now,
                harness.run(selected));
        latest = combinedResult;
        return new SafetyPackResult(now, selected.size(), seen.size(), unseen.size(),
                seenResult, unseenResult, combinedResult);
    }
    public RunResult latest() {
        return latest;
    }

    private Path resolveFilename(String supplied) {
        String filename = Path.of(supplied).getFileName().toString();
        Path candidate = datasetRoot.resolve(filename).normalize();
        if (!candidate.startsWith(datasetRoot)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid dataset filename.");
        }
        return candidate;
    }

    private static boolean isBlank(String value) { return value == null || value.isBlank(); }
    private static String emptyToNull(String value) { return isBlank(value) ? null : value.trim(); }
}