import dev.wgapps.settings.Kinds;
import java.util.Map;
import java.util.TreeMap;

/** Plain checks, run with java -ea by tools/build-settings-app.sh. */
public final class KindsTest {
    private static void check(boolean condition, String what) {
        if (!condition) throw new AssertionError(what);
    }

    public static void main(String[] args) {
        Map<String, String> parsed = Kinds.parse("org.b.app 2d\ncom.a.app xr\ncom.a.app 2d\nbad pkg xr\ncom.c.app auto\nnospace\n");
        check(parsed.size() == 2, "only valid lines: " + parsed);
        check("2d".equals(parsed.get("com.a.app")), "the last line of a package wins");
        check("2d".equals(parsed.get("org.b.app")), "org.b.app");

        check(Kinds.serialize(parsed).equals("com.a.app 2d\norg.b.app 2d\n"), "sorted lines: " + Kinds.serialize(parsed));
        check(Kinds.parse(Kinds.serialize(parsed)).equals(parsed), "round trip");

        Map<String, String> kinds = new TreeMap<>();
        Kinds.set(kinds, "com.a.app", "xr");
        check("xr".equals(kinds.get("com.a.app")), "set xr");
        Kinds.set(kinds, "com.a.app", null);
        check(kinds.isEmpty(), "null means detected");
        Kinds.set(kinds, "com.a.app", "auto");
        check(kinds.isEmpty(), "anything else is not a kind");

        Map<String, String> bad = new TreeMap<>();
        bad.put("../x", "xr");
        bad.put("com.a.app", "both");
        check(Kinds.serialize(bad).isEmpty(), "the host would refuse these");
        System.out.println("KindsTest ok");
    }
}
