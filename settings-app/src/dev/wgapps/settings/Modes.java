package dev.wgapps.settings;

/**
 * The container's mode, as the host's saved mode file: one word, "steam" or "vr". Anything else is steam,
 * the default. Plain Java, tested on the build host.
 */
public final class Modes {
    public static final String STEAM = "steam";
    public static final String VR = "vr";

    private Modes() {}

    /** The mode a file's text names; steam when it is empty or says anything else. */
    public static String parse(String text) {
        if (text == null) return STEAM;
        String word = text.trim();
        int end = word.indexOf('\n');
        if (end >= 0) word = word.substring(0, end).trim();
        return VR.equals(word) ? VR : STEAM;
    }

    /** What the screen writes for a mode. */
    public static String serialize(String mode) {
        return (VR.equals(mode) ? VR : STEAM) + "\n";
    }
}
