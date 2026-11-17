package dev.wgapps.settings;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * The per-app device profiles, as lines of "package key=value" (the format of the host's apps.conf),
 * and the presets the screen offers. Plain Java: no Android types, so it is tested on the build host.
 */
public final class Profiles {
    /** The keys the host accepts, in the order they are written. */
    public static final String[] KEYS = {"model", "manufacturer", "brand", "device"};

    /** A device to pose as: one value per key, null for a key it leaves alone. */
    public static final class Preset {
        public final String name;
        public final String summary;
        public final String[] values;

        Preset(String name, String summary, String... values) {
            this.name = name;
            this.summary = summary;
            this.values = values;
        }
    }

    public static final String DEFAULT = "Default";
    public static final String CUSTOM = "Custom";

    public static final Preset[] PRESETS = {
        new Preset("Meta Quest 3", "Quest 3, Oculus", "Quest 3", "Oculus", "oculus", "eureka"),
        new Preset("Meta Quest 3S", "Quest 3S, Oculus", "Quest 3S", "Oculus", "oculus", "sepulcher"),
        new Preset("Meta Quest Pro", "Quest Pro, Oculus", "Quest Pro", "Oculus", "oculus", "seacliff"),
        new Preset("Meta Quest 2", "Quest 2, Oculus", "Quest 2", "Oculus", "oculus", "hollywood"),
        new Preset("Pico 4", "A8110, PICO", "A8110", "PICO", "PICO", null),
        new Preset("Pico 4 Ultra", "A9210, PICO", "A9210", "PICO", "PICO", null),
    };

    private static final Pattern VALUE = Pattern.compile("[A-Za-z0-9 ._+()/:-]{1,91}");
    private static final Pattern PACKAGE = Pattern.compile("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+");

    private Profiles() {}

    /** What the host takes as a value: 1 to 91 safe characters, no space at either end. */
    public static boolean validValue(String value) {
        return value != null && VALUE.matcher(value).matches()
                && !value.startsWith(" ") && !value.endsWith(" ");
    }

    public static boolean validPackage(String name) {
        return name != null && name.length() <= 54 && PACKAGE.matcher(name).matches();
    }

    private static boolean validKey(String key) {
        return Arrays.asList(KEYS).contains(key);
    }

    /** package, then key, then value; in the order first seen. Lines that are not valid are left out. */
    public static Map<String, Map<String, String>> byPackage(String text) {
        Map<String, Map<String, String>> result = new LinkedHashMap<>();
        for (String line : text.split("\n")) {
            int space = line.indexOf(' ');
            if (space < 0) continue;
            String pkg = line.substring(0, space);
            String rest = line.substring(space + 1);
            int equals = rest.indexOf('=');
            if (equals < 0) continue;
            String key = rest.substring(0, equals);
            String value = rest.substring(equals + 1);
            if (!validPackage(pkg) || !validKey(key) || !validValue(value)) continue;
            Map<String, String> keys = result.get(pkg);
            if (keys == null) {
                keys = new LinkedHashMap<>();
                result.put(pkg, keys);
            }
            keys.put(key, value);
        }
        return result;
    }

    public static String serialize(Map<String, Map<String, String>> all) {
        StringBuilder out = new StringBuilder();
        for (Map.Entry<String, Map<String, String>> entry : all.entrySet()) {
            for (String key : KEYS) {
                String value = entry.getValue().get(key);
                if (value != null) out.append(entry.getKey()).append(' ').append(key).append('=').append(value).append('\n');
            }
        }
        return out.toString();
    }

    /** The preset a package's keys are exactly, DEFAULT for none, CUSTOM for anything else. */
    public static String current(Map<String, String> keys) {
        if (keys == null || keys.isEmpty()) return DEFAULT;
        for (Preset preset : PRESETS) {
            boolean same = true;
            for (int i = 0; i < KEYS.length; i++) {
                String want = preset.values[i];
                String have = keys.get(KEYS[i]);
                if (want == null ? have != null : !want.equals(have)) same = false;
            }
            if (same) return preset.name;
        }
        return CUSTOM;
    }

    public static void clear(Map<String, Map<String, String>> all, String pkg) {
        all.remove(pkg);
    }

    public static void setPreset(Map<String, Map<String, String>> all, String pkg, Preset preset) {
        Map<String, String> keys = new LinkedHashMap<>();
        for (int i = 0; i < KEYS.length; i++) {
            if (preset.values[i] != null) keys.put(KEYS[i], preset.values[i]);
        }
        all.put(pkg, keys);
    }

    /** Only the model; false (and nothing changed) when the host would not take it. */
    public static boolean setCustom(Map<String, Map<String, String>> all, String pkg, String model) {
        if (!validValue(model)) return false;
        Map<String, String> keys = new LinkedHashMap<>();
        keys.put("model", model);
        all.put(pkg, keys);
        return true;
    }
}
