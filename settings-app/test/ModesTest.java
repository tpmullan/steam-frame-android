import dev.wgapps.settings.Modes;

/** Plain checks, run with java -ea by tools/build-settings-app.sh. */
public final class ModesTest {
    private static void check(boolean condition, String what) {
        if (!condition) throw new AssertionError(what);
    }

    public static void main(String[] args) {
        check(Modes.parse("vr\n").equals("vr"), "vr");
        check(Modes.parse("  vr  ").equals("vr"), "spaces");
        check(Modes.parse("steam\n").equals("steam"), "steam");
        check(Modes.parse("").equals("steam"), "empty is steam");
        check(Modes.parse(null).equals("steam"), "null is steam");
        check(Modes.parse("VR").equals("steam"), "case matters, like the host");
        check(Modes.parse("vr extra").equals("steam"), "one word only");
        check(Modes.parse("vr\nsteam\n").equals("vr"), "the first line");
        check(Modes.serialize("vr").equals("vr\n"), "serialize vr");
        check(Modes.serialize("steam").equals("steam\n"), "serialize steam");
        check(Modes.serialize("anything").equals("steam\n"), "anything else is steam");
        System.out.println("ModesTest ok");
    }
}
