package dev.wgapps.settings;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * The file the host shares with Android: device-profiles.conf in the folder bin/wgapps mounts at
 * /data/local/tmp/host_share. The host mirrors its settings to it; wgapps-profiles imports a changed one.
 */
public final class ProfilesFile {
    public static final String DEFAULT_PATH = "/data/local/tmp/host_share/device-profiles.conf";
    /** Bigger than any list of overrides; the host refuses more than this too. */
    static final int MAX_BYTES = 65536;

    private final File file;

    public ProfilesFile() {
        this(new File(DEFAULT_PATH));
    }

    public ProfilesFile(File file) {
        this.file = file;
    }

    /** The file's text; empty when there is none yet, or it is not readable or not sane. */
    public String load() {
        if (!file.isFile() || file.length() > MAX_BYTES) return "";
        try (InputStream in = new FileInputStream(file)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int got;
            while ((got = in.read(buffer)) > 0) out.write(buffer, 0, got);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    /** Written beside the file and renamed over it, so the host never reads half of it. */
    public void save(String text) throws IOException {
        File tmp = new File(file.getParentFile(), "." + file.getName() + ".app");
        try (OutputStream out = new FileOutputStream(tmp)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
        // The host is another user as far as Android is concerned.
        tmp.setReadable(true, false);
        if (!tmp.renameTo(file)) {
            tmp.delete();
            throw new IOException("cannot replace " + file);
        }
    }
}
