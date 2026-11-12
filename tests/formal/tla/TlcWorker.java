import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Base64;
import java.util.concurrent.FutureTask;

/** Runs each request with its own copy of TLC's static state. */
public final class TlcWorker {
    private static final int MAXIMUM_REQUEST_BYTES = 65536;

    /** The binary payload preserves UTF-8 argument boundaries. */
    private record Request(long identifier, Path directory, String[] arguments) {}

    private static Request readRequest(BufferedInputStream input) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        int value;
        while ((value = input.read()) != -1 && value != '\n') {
            if (line.size() == MAXIMUM_REQUEST_BYTES - 1) {
                throw new IOException("TLC worker request exceeds its size limit");
            }
            line.write(value);
        }
        if (value == -1) {
            if (line.size() == 0) return null;
            throw new IOException("Incomplete TLC worker request");
        }
        String header = line.toString(StandardCharsets.US_ASCII);
        int separator = header.indexOf(' ');
        if (separator < 1) {
            throw new IOException("Missing TLC worker request identifier");
        }
        long identifier = Long.parseLong(header.substring(0, separator));
        byte[] bytes = Base64.getDecoder().decode(header.substring(separator + 1));
        var payload = new DataInputStream(new ByteArrayInputStream(bytes));
        var fields = new ArrayList<String>();
        while (payload.available() > 0) {
            int length = payload.readInt();
            if (length < 0 || length > payload.available()) {
                throw new IOException("Invalid TLC worker argument length");
            }
            byte[] field = payload.readNBytes(length);
            fields.add(StandardCharsets.UTF_8.newDecoder()
                    .decode(ByteBuffer.wrap(field)).toString());
        }
        if (identifier <= 0 || fields.size() < 2) {
            throw new IOException("Invalid TLC worker request");
        }
        Path directory = Path.of(fields.getFirst());
        String[] arguments = fields.subList(1, fields.size()).toArray(String[]::new);
        return new Request(identifier, directory, arguments);
    }

    private static int check(URLClassLoader loader, String[] arguments)
            throws ReflectiveOperationException {
        if (arguments[0].equals("--peri-scribe-frame")) {
            if (arguments.length != 5 && arguments.length != 6) {
                throw new IllegalArgumentException("Invalid frame request");
            }
            Class<?> frame = loader.loadClass("FrameChecker");
            boolean checked = (boolean) frame
                    .getMethod("check", String.class, String.class, String.class, String.class, String.class)
                    .invoke(null, arguments[1], arguments[2], arguments[3], arguments[4],
                            arguments.length == 6 ? arguments[5] : "TEXT");
            return checked ? 0 : 125;
        }
        Class<?> checkerType = loader.loadClass("tlc2.TLC");
        Object checker = checkerType.getConstructor().newInstance();
        boolean parsed = (boolean) checkerType
                .getMethod("handleParameters", String[].class)
                .invoke(checker, (Object) arguments);
        if (!parsed) return 1;
        String main = (String) checkerType.getMethod("getMainFile").invoke(checker);
        String directory = (String) loader.loadClass("util.FileUtil")
                .getMethod("parseDirname", String.class).invoke(null, main);
        Class<?> resolverType = loader.loadClass("util.SimpleFilenameToStream");
        Object resolver = directory.isEmpty()
                ? resolverType.getConstructor().newInstance()
                : resolverType.getConstructor(String.class).newInstance(directory);
        checkerType.getMethod("setResolver", loader.loadClass("util.FilenameToStream"))
                .invoke(checker, resolver);
        int result = (int) checkerType.getMethod("process").invoke(checker);
        return (int) loader.loadClass("tlc2.output.EC$ExitStatus")
                .getMethod("errorConstantToExitStatus", int.class).invoke(null, result);
    }

    private static PrintStream diagnostics(Path directory, String name)
            throws IOException {
        return new PrintStream(
                Files.newOutputStream(
                        directory.resolve(name), StandardOpenOption.CREATE_NEW),
                true,
                StandardCharsets.UTF_8);
    }

    private static int run(URL[] classpath, Request request) throws Exception {
        String previousDirectory = System.getProperty("java.io.tmpdir");
        PrintStream stdout = System.out;
        PrintStream stderr = System.err;
        ThreadGroup group = new ThreadGroup("tlc-request-" + request.identifier());
        System.setProperty("java.io.tmpdir", request.directory().toString());
        var parent = ClassLoader.getPlatformClassLoader();
        try (var loader = new URLClassLoader(classpath, parent);
                var output = diagnostics(request.directory(), "stdout.log");
                var errors = diagnostics(request.directory(), "stderr.log")) {
            System.setOut(output);
            System.setErr(errors);
            var task = new FutureTask<>(() -> check(loader, request.arguments()));
            Thread worker = new Thread(group, task, "tlc-checker");
            worker.setContextClassLoader(loader);
            worker.start();
            int result = task.get();
            worker.join();
            for (Thread thread : Thread.getAllStackTraces().keySet()) {
                if (thread.getContextClassLoader() == loader
                        || group.parentOf(thread.getThreadGroup())) {
                    throw new IOException("TLC request left a model thread " + thread);
                }
            }
            output.close();
            errors.close();
            if (output.checkError() || errors.checkError()) {
                throw new IOException("TLC request could not write its diagnostics");
            }
            return result;
        } finally {
            System.setProperty("java.io.tmpdir", previousDirectory);
            System.setOut(stdout);
            System.setErr(stderr);
        }
    }

    /** A result becomes visible only after the request has released its resources. */
    public static void main(String[] arguments) throws Exception {
        URL[] classpath = {
            Path.of(arguments[0]).toUri().toURL(),
            TlcWorker.class.getProtectionDomain().getCodeSource().getLocation(),
        };
        var input = new BufferedInputStream(System.in);
        Request request;
        while ((request = readRequest(input)) != null) {
            int result = run(classpath, request);
            System.out.println(request.identifier() + " " + result);
            if (System.out.checkError()) {
                throw new IOException("Cannot send TLC worker result");
            }
        }
        // JVM-wide RMI services can survive individual model lifetimes.
        System.exit(0);
    }
}
