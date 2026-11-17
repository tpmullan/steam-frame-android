import dev.wgapps.settings.Labels;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Plain checks, run with java -ea by tools/build-settings-app.sh. */
public final class LabelsTest {
    private static void check(boolean condition, String what) {
        if (!condition) throw new AssertionError(what);
    }

    private static List<String[]> rows(String... pairs) {
        List<String[]> rows = new ArrayList<>();
        for (int i = 0; i < pairs.length; i += 2) rows.add(new String[] {pairs[i], pairs[i + 1]});
        return rows;
    }

    public static void main(String[] args) {
        // One line per app, sorted by package.
        check(Labels.serialize(rows("org.b.app", "Bee", "com.a.app", "Ay")).equals("com.a.app\tAy\norg.b.app\tBee\n"), "sorted lines");

        // The first row of a package wins.
        check(Labels.serialize(rows("com.a.app", "First", "com.a.app", "Second")).equals("com.a.app\tFirst\n"), "first wins");

        // Packages the host would refuse are left out.
        check(Labels.serialize(rows("bad pkg", "X", "../x", "Y", ".hidden", "Z", "nodots", "W")).isEmpty(), "invalid packages");

        // A label cannot break the line format.
        String tricky = Labels.serialize(rows("com.a.app", "Two\tcolumns\nand a line\r\nbreak\u0001"));
        check(tricky.equals("com.a.app\tTwo columns and a line break\n"), "control characters: " + tricky.replace("\t", "<TAB>"));
        check(tricky.split("\n").length == 1 && tricky.split("\t").length == 2, "one row, two columns");

        // Empty after cleaning: left out, not written as an empty name.
        check(Labels.serialize(rows("com.a.app", " \t\n ")).isEmpty(), "blank label");
        check(Labels.serialize(rows("com.a.app", null)).isEmpty(), "null label");

        // Long labels are cut at 60 characters (by code point, never mid-surrogate).
        StringBuilder long80 = new StringBuilder();
        for (int i = 0; i < 80; i++) long80.append('a');
        String cut = Labels.serialize(rows("com.a.app", long80.toString()));
        check(cut.equals("com.a.app\t" + long80.substring(0, 60) + "\n"), "cut at 60");
        StringBuilder emoji = new StringBuilder();
        for (int i = 0; i < 70; i++) emoji.appendCodePoint(0x1F600);
        String emojiLine = Labels.serialize(rows("com.a.app", emoji.toString()));
        check(emojiLine.codePointCount(0, emojiLine.length()) == "com.a.app\t".length() + 60 + 1, "emoji cut by code point");

        // Ordinary text and non-ASCII letters pass through.
        check(Labels.serialize(rows("com.a.app", "Café ゲーム")).equals("com.a.app\tCafé ゲーム\n"), "unicode kept");

        // Empty input.
        check(Labels.serialize(new ArrayList<>()).isEmpty(), "empty");
        check(Labels.serialize(Arrays.<String[]>asList(null, new String[] {"only"})).isEmpty(), "malformed rows skipped");

        System.out.println("LabelsTest ok");
    }
}
