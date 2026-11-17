package dev.wgapps.shell;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * The apps the host offers, from the file `wgapps apps push` writes to the shared folder
 * (/data/local/tmp/host_share/apps.tsv inside Android): one app per line,
 * {@code package TAB label TAB package/activity TAB kind} (kind xr or 2d). Nothing here needs
 * Android, so the tests run on the build machine.
 */
public final class Catalog {
    public static final String DEFAULT_PATH = "/data/local/tmp/host_share/apps.tsv";

    private static final Pattern PACKAGE =
            Pattern.compile("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+$");
    private static final Pattern ACTIVITY = Pattern.compile("^[A-Za-z0-9_.$]+$");
    private static final int PACKAGE_MAX = 54;
    private static final int LABEL_MAX = 60;

    public static final class Entry {
        public final String packageName;
        public final String label;
        public final String activity;
        public final boolean xr;

        Entry(String packageName, String label, String activity, boolean xr) {
            this.packageName = packageName;
            this.label = label;
            this.activity = activity;
            this.xr = xr;
        }

        /** The component in the form `am start -n` takes. */
        public String component() {
            return packageName + "/" + activity;
        }
    }

    private Catalog() {}

    /** Entries of TEXT, malformed lines skipped, one per package (the first wins), by label. */
    public static List<Entry> parse(String text) {
        List<Entry> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        if (text == null) return out;
        for (String raw : text.split("\n")) {
            String line = raw.replace("\r", "");
            String[] cols = line.split("\t", -1);
            if (cols.length < 3) continue;
            String pkg = cols[0].trim();
            String label = clean(cols[1]);
            String component = cols[2].trim();
            int slash = component.indexOf('/');
            if (slash < 1) continue;
            String componentPackage = component.substring(0, slash);
            String activity = component.substring(slash + 1);
            if (!PACKAGE.matcher(pkg).matches() || pkg.length() > PACKAGE_MAX) continue;
            if (!pkg.equals(componentPackage) || !ACTIVITY.matcher(activity).matches()) continue;
            if (!seen.add(pkg)) continue;
            if (label.isEmpty()) label = pkg.substring(pkg.lastIndexOf('.') + 1);
            boolean xr = cols.length > 3 && cols[3].trim().equals("xr");
            out.add(new Entry(pkg, label, activity, xr));
        }
        Collections.sort(out, new Comparator<Entry>() {
            @Override
            public int compare(Entry a, Entry b) {
                int c = a.label.toLowerCase(Locale.ROOT).compareTo(b.label.toLowerCase(Locale.ROOT));
                return c != 0 ? c : a.packageName.compareTo(b.packageName);
            }
        });
        return out;
    }

    private static String clean(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) if (c >= 0x20 && c != 0x7f) b.append(c);
        String t = b.toString().trim();
        return t.length() > LABEL_MAX ? t.substring(0, LABEL_MAX) : t;
    }
}
