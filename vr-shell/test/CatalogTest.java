import dev.wgapps.shell.Catalog;

import java.util.List;

/** Run with `java -ea`: tools/build-shell.sh does. */
public class CatalogTest {
    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
    }

    static String line(String pkg, String label, String comp, String kind) {
        return pkg + "\t" + label + "\t" + comp + "\t" + kind + "\n";
    }

    public static void main(String[] args) {
        String good = line("org.b.app", "Banana", "org.b.app/.Main", "2d")
                + line("org.a.app", "apple", "org.a.app/org.a.app.Main", "xr");
        List<Catalog.Entry> apps = Catalog.parse(good);
        check(apps.size() == 2, "two apps");
        check(apps.get(0).label.equals("apple") && apps.get(1).label.equals("Banana"), "by label, any case");
        check(apps.get(0).xr && !apps.get(1).xr, "kind");
        check(apps.get(1).component().equals("org.b.app/.Main"), "component");

        check(Catalog.parse("").isEmpty() && Catalog.parse(null).isEmpty(), "empty and null");
        check(Catalog.parse("no tabs at all\n").isEmpty(), "no tabs");
        check(Catalog.parse("a.b\tx\n").size() == 0, "two columns is not enough");

        // Rejected: bad package, package differing from the component's, bad activity, no slash.
        check(Catalog.parse(line("nodots", "x", "nodots/.A", "2d")).isEmpty(), "package needs a dot");
        check(Catalog.parse(line("a.b", "x", "c.d/.A", "2d")).isEmpty(), "component of another package");
        check(Catalog.parse(line("a.b", "x", "a.b/.A B", "2d")).isEmpty(), "bad activity");
        check(Catalog.parse(line("a.b", "x", "a.b.A", "2d")).isEmpty(), "no slash");
        check(Catalog.parse(line("../../a.b", "x", "../../a.b/.A", "2d")).isEmpty(), "path-like package");

        // Duplicates: the first wins. CRLF and control characters are cleaned.
        List<Catalog.Entry> dup = Catalog.parse(line("a.b", "First", "a.b/.A", "2d") + line("a.b", "Second", "a.b/.B", "xr"));
        check(dup.size() == 1 && dup.get(0).label.equals("First"), "first of a duplicate");
        List<Catalog.Entry> crlf = Catalog.parse("a.b\tTa\u0001b\t a.b/.A\t2d\r\n");
        check(crlf.size() == 1 && crlf.get(0).label.equals("Tab") && crlf.get(0).component().equals("a.b/.A"), "crlf and controls");

        // Missing label falls back to the last package part; a missing or odd kind is flat.
        List<Catalog.Entry> bare = Catalog.parse("a.b.thing\t\ta.b.thing/.A\n");
        check(bare.get(0).label.equals("thing") && !bare.get(0).xr, "label fallback, default kind");
        check(!Catalog.parse(line("a.b", "x", "a.b/.A", "weird")).get(0).xr, "unknown kind is 2d");

        // Labels are cut, not trusted.
        StringBuilder longLabel = new StringBuilder();
        for (int i = 0; i < 500; i++) longLabel.append('x');
        check(Catalog.parse(line("a.b", longLabel.toString(), "a.b/.A", "2d")).get(0).label.length() == 60, "label cut");
        System.out.println("CatalogTest ok");
    }
}
