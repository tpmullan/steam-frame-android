import dev.wgapps.settings.ProfilesFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.file.Files;

/** Run by tools/build-settings-app.sh with `java -ea`. */
public class ProfilesFileTest {
    static int failures;

    static void equal(Object actual, Object expected, String what) {
        if (!String.valueOf(actual).equals(String.valueOf(expected))) {
            System.out.println("FAIL " + what + ": " + actual + " != " + expected);
            failures++;
        }
    }

    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("profiles").toFile();
        File target = new File(dir, "device-profiles.conf");
        ProfilesFile file = new ProfilesFile(target);

        equal(file.load(), "", "no file yet");
        file.save("com.a.b model=Quest 3\n");
        equal(file.load(), "com.a.b model=Quest 3\n", "saved text loads");
        equal(target.canRead(), true, "readable");
        file.save("");
        equal(file.load(), "", "saving nothing empties it");
        file.save("com.a.b model=é\n");
        equal(file.load(), "com.a.b model=é\n", "utf-8 survives");

        String[] left = dir.list();
        java.util.Arrays.sort(left);
        equal(java.util.Arrays.toString(left), "[device-profiles.conf]", "no temporary file is left behind");

        // A file the host would refuse is not read either.
        try (FileOutputStream out = new FileOutputStream(target)) {
            out.write(new byte[65537]);
        }
        equal(file.load(), "", "oversized file reads as empty");

        // Saving where it cannot: an error, not a half-written file.
        File gone = new File(dir, "missing-dir/device-profiles.conf");
        try {
            new ProfilesFile(gone).save("x");
            equal("no exception", "exception", "saving into a missing directory fails");
        } catch (java.io.IOException expected) {
            // fine
        }

        // A directory in the way of the file: rename fails, the temporary file is removed.
        File blocked = new File(dir, "blocked");
        File inTheWay = new File(blocked, "device-profiles.conf");
        inTheWay.mkdirs();
        new File(inTheWay, "child").createNewFile();
        try {
            new ProfilesFile(inTheWay).save("x");
            equal("no exception", "exception", "saving over a non-empty directory fails");
        } catch (java.io.IOException expected) {
            equal(java.util.Arrays.toString(blocked.list()), "[device-profiles.conf]", "temporary file removed after a failed rename");
        }

        if (failures > 0) {
            System.out.println(failures + " failure(s)");
            System.exit(1);
        }
        System.out.println("ProfilesFileTest: all checks passed");
    }
}
