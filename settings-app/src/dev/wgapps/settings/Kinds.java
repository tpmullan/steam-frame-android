package dev.wgapps.settings;

import java.util.Map;
import java.util.TreeMap;

/**
 * The per-app launch type the VR shell uses, as lines of "package xr" or "package 2d" (the format of
 * the host's apps-kind file). No line means the host detects it. Plain Java, tested on the build host.
 */
public final class Kinds {
    public static final String XR = "xr";
    public static final String FLAT = "2d";

    private Kinds() {}

    public static boolean validKind(String kind) {
        return XR.equals(kind) || FLAT.equals(kind);
    }

    /** package to kind; lines the host would refuse are left out and the last line of a package wins. */
    public static Map<String, String> parse(String text) {
        Map<String, String> result = new TreeMap<>();
        for (String line : text.split("\n")) {
            int space = line.indexOf(' ');
            if (space < 0) continue;
            String pkg = line.substring(0, space);
            String kind = line.substring(space + 1);
            if (Profiles.validPackage(pkg) && validKind(kind)) result.put(pkg, kind);
        }
        return result;
    }

    public static String serialize(Map<String, String> kinds) {
        StringBuilder out = new StringBuilder();
        for (Map.Entry<String, String> entry : new TreeMap<>(kinds).entrySet()) {
            if (Profiles.validPackage(entry.getKey()) && validKind(entry.getValue())) {
                out.append(entry.getKey()).append(' ').append(entry.getValue()).append('\n');
            }
        }
        return out.toString();
    }

    /** null (or anything that is not a kind) puts the app back to "detected". */
    public static void set(Map<String, String> kinds, String pkg, String kind) {
        if (validKind(kind)) kinds.put(pkg, kind);
        else kinds.remove(pkg);
    }
}
