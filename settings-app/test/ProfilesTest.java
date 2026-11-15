import dev.wgapps.settings.Profiles;
import java.util.LinkedHashMap;
import java.util.Map;

/** Run by tools/build-settings-app.sh with `java -ea`: prints failures and exits 1. */
public class ProfilesTest {
    static int failures;

    static void check(boolean ok, String what) {
        if (!ok) {
            System.out.println("FAIL " + what);
            failures++;
        }
    }

    static void equal(Object actual, Object expected, String what) {
        if (!String.valueOf(actual).equals(String.valueOf(expected))) {
            System.out.println("FAIL " + what + ": " + actual + " != " + expected);
            failures++;
        }
    }

    public static void main(String[] args) {
        String quest3 = "com.a.b model=Quest 3\ncom.a.b manufacturer=Oculus\ncom.a.b brand=oculus\ncom.a.b device=eureka\n";

        // Parse and serialize round trip, in a stable key order.
        String shuffled = "com.a.b device=eureka\ncom.a.b brand=oculus\ncom.a.b manufacturer=Oculus\ncom.a.b model=Quest 3\n";
        equal(Profiles.serialize(Profiles.byPackage(shuffled)), quest3, "round trip sorts keys");
        equal(Profiles.serialize(Profiles.byPackage("")), "", "empty");

        // What the host would drop is dropped; lines for packages the screen does not list survive.
        String mixed = "no equals\n\nbad pkg model=x\ncom.a.b bogus=1\ncom.a.b model=a;b\ncom.z.z model=Kept\ncom.a.b brand=Meta\n";
        equal(Profiles.serialize(Profiles.byPackage(mixed)), "com.z.z model=Kept\ncom.a.b brand=Meta\n", "invalid lines dropped, packages in the order first seen");
        equal(Profiles.serialize(Profiles.byPackage("com.a.b model=First\ncom.a.b model=Second\n")), "com.a.b model=Second\n", "last wins");
        equal(Profiles.serialize(Profiles.byPackage("com.a.b model=Quest 3\r\n")), "", "a carriage return is not a valid value");

        // Which preset a package is on.
        Map<String, Map<String, String>> all = Profiles.byPackage(quest3);
        equal(Profiles.current(all.get("com.a.b")), "Meta Quest 3", "recognises Quest 3");
        equal(Profiles.current(all.get("com.none")), Profiles.DEFAULT, "no lines is the default");
        equal(Profiles.current(new LinkedHashMap<String, String>()), Profiles.DEFAULT, "empty is the default");
        for (Profiles.Preset preset : Profiles.PRESETS) {
            Map<String, Map<String, String>> one = new LinkedHashMap<>();
            Profiles.setPreset(one, "com.a.b", preset);
            equal(Profiles.current(one.get("com.a.b")), preset.name, "each preset is recognised: " + preset.name);
            Map<String, Map<String, String>> again = Profiles.byPackage(Profiles.serialize(one));
            equal(Profiles.current(again.get("com.a.b")), preset.name, "and survives the file: " + preset.name);
        }
        equal(Profiles.current(Profiles.byPackage("com.a.b model=Quest 3\n").get("com.a.b")), Profiles.CUSTOM, "a model alone is custom");
        equal(Profiles.current(Profiles.byPackage("com.a.b model=Quest 3\ncom.a.b manufacturer=Oculus\ncom.a.b brand=oculus\ncom.a.b device=other\n").get("com.a.b")), Profiles.CUSTOM, "a changed key is custom");
        // Pico presets leave device alone; a device line would make it custom.
        equal(Profiles.current(Profiles.byPackage("com.a.b model=A8110\ncom.a.b manufacturer=PICO\ncom.a.b brand=PICO\ncom.a.b device=x\n").get("com.a.b")), Profiles.CUSTOM, "extra key is custom");

        // Choosing replaces only that package.
        Map<String, Map<String, String>> two = Profiles.byPackage("com.a.b model=Old\ncom.c.d model=Other\n");
        Profiles.setPreset(two, "com.a.b", Profiles.PRESETS[0]);
        equal(Profiles.serialize(two), quest3 + "com.c.d model=Other\n", "preset replaces only its package");
        Profiles.clear(two, "com.a.b");
        equal(Profiles.serialize(two), "com.c.d model=Other\n", "default removes only its package");
        Profiles.clear(two, "com.not.there");
        equal(Profiles.serialize(two), "com.c.d model=Other\n", "clearing nothing changes nothing");

        // Custom model.
        Map<String, Map<String, String>> custom = Profiles.byPackage("com.a.b brand=Meta\n");
        check(Profiles.setCustom(custom, "com.a.b", "My Headset 2"), "custom accepted");
        equal(Profiles.serialize(custom), "com.a.b model=My Headset 2\n", "custom replaces the package's lines");
        check(!Profiles.setCustom(custom, "com.a.b", "bad;value"), "custom refused");
        equal(Profiles.serialize(custom), "com.a.b model=My Headset 2\n", "a refused custom changes nothing");

        // The host's rules for values.
        String[] good = {"Quest 3", "a.b_c+(d)/e:f-g", "x", "v".repeat(91)};
        for (String value : good) check(Profiles.validValue(value), "valid value " + value);
        String[] bad = {"", " lead", "trail ", "a'b", "a;b", "$(x)", "a\nb", "back\\slash", "quo\"te", "v".repeat(92), "tab\t", "é"};
        for (String value : bad) check(!Profiles.validValue(value), "invalid value " + value.replace("\n", "\\n"));
        check(!Profiles.validValue(null), "null value");

        // The host's rules for packages.
        String[] goodPackages = {"com.igalia.wolvic.vanilla", "a.b", "com.a_b.c9"};
        for (String name : goodPackages) check(Profiles.validPackage(name), "valid package " + name);
        String[] badPackages = {"", "nodots", "com..x", ".com.x", "com.x.", "9a.b", "bad pkg.x", "com.x;y", "com." + "a".repeat(51)};
        for (String name : badPackages) check(!Profiles.validPackage(name), "invalid package " + name);
        check(Profiles.validPackage("com." + "a".repeat(50)), "a 54-character package");

        // Every preset value is one the host accepts.
        for (Profiles.Preset preset : Profiles.PRESETS) {
            for (String value : preset.values) check(value == null || Profiles.validValue(value), "preset value valid: " + value);
            check(preset.values.length == Profiles.KEYS.length, "a value per key: " + preset.name);
            check(preset.values[0] != null, "every preset has a model: " + preset.name);
        }

        if (failures > 0) {
            System.out.println(failures + " failure(s)");
            System.exit(1);
        }
        System.out.println("ProfilesTest: all checks passed");
    }
}
