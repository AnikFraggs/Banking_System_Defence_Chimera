import java.io.PrintWriter;
import java.util.Arrays;
import java.util.List;
import org.junit.platform.engine.DiscoverySelector;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

public final class TestRunner {
    public static void main(String[] classNames) {
        List<DiscoverySelector> selectors = Arrays.stream(classNames)
                .map(name -> (DiscoverySelector) DiscoverySelectors.selectClass(name))
                .toList();
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
                .selectors(selectors)
                .build();
        SummaryGeneratingListener listener = new SummaryGeneratingListener();
        Launcher launcher = LauncherFactory.create();
        launcher.registerTestExecutionListeners(listener);
        launcher.execute(request);

        TestExecutionSummary summary = listener.getSummary();
        summary.printTo(new PrintWriter(System.out, true));
        summary.printFailuresTo(new PrintWriter(System.out, true));
        System.out.printf("Tests: %d passed, %d failed, %d skipped%n",
                summary.getTestsSucceededCount(), summary.getTestsFailedCount(), summary.getTestsSkippedCount());
        if (summary.getTestsFailedCount() > 0 || summary.getTestsFoundCount() == 0) {
            System.exit(1);
        }
    }
}
