import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import org.junit.jupiter.api.Test;

public final class TestRunner {
    public static void main(String[] classNames) throws Exception {
        int passed = 0, failed = 0;
        for (String className : classNames) {
            Class<?> type = Class.forName(className);
            Constructor<?> constructor = type.getDeclaredConstructor();
            constructor.setAccessible(true);
            Object instance = constructor.newInstance();
            for (Method method : type.getDeclaredMethods()) {
                if (!method.isAnnotationPresent(Test.class)) continue;
                method.setAccessible(true);
                try {
                    method.invoke(instance);
                    System.out.println("PASS " + className + "#" + method.getName());
                    passed++;
                } catch (InvocationTargetException error) {
                    System.err.println("FAIL " + className + "#" + method.getName() + ": " + error.getCause());
                    failed++;
                }
            }
        }
        System.out.println("Tests: " + passed + " passed, " + failed + " failed");
        if (failed > 0) System.exit(1);
    }
}