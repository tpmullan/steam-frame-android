package dev.wgapps.settings;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;

/**
 * The names of the apps a user can open, as the host's app catalog reads them (app-labels.conf in the
 * shared folder): one "package TAB label" line per app. Android's command line gives the host no label
 * text, so this app, which can ask the PackageManager, writes it.
 */
public final class Labels {
    /** Longer labels are cut; a launcher tile has no room for more. */
    static final int MAX_LABEL = 60;

    private Labels() {}

    /** One line of plain text: control characters (tab and newline too) become spaces, ends trimmed. */
    static String clean(String label) {
        if (label == null) return "";
        StringBuilder out = new StringBuilder();
        label.codePoints().limit(MAX_LABEL * 4L).forEach(cp -> {
            boolean control = cp < 0x20 || (cp >= 0x7f && cp < 0xa0) || cp == 0x2028 || cp == 0x2029;
            out.appendCodePoint(control ? ' ' : cp);
        });
        String text = out.toString().trim().replaceAll(" {2,}", " ");
        if (text.codePointCount(0, text.length()) > MAX_LABEL) {
            text = text.substring(0, text.offsetByCodePoints(0, MAX_LABEL)).trim();
        }
        return text;
    }

    /**
     * @param rows each {package, label}; a package the host would not accept, or a label that is empty
     *     after cleaning, is left out, and the first row of a package wins
     */
    public static String serialize(List<String[]> rows) {
        TreeMap<String, String> byPackage = new TreeMap<>();
        for (String[] row : rows) {
            if (row == null || row.length != 2 || !Profiles.validPackage(row[0])) continue;
            String label = clean(row[1]);
            if (label.isEmpty() || byPackage.containsKey(row[0])) continue;
            byPackage.put(row[0], label);
        }
        StringBuilder text = new StringBuilder();
        for (String pkg : new ArrayList<>(byPackage.keySet())) {
            text.append(pkg).append('\t').append(byPackage.get(pkg)).append('\n');
        }
        return text.toString();
    }
}
