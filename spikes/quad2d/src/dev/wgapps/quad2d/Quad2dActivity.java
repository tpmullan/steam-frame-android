package dev.wgapps.quad2d;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import java.nio.ByteBuffer;

/**
 * Spike S4. Creates a VirtualDisplay that draws into an ImageReader (the buffer a 3D shell would turn
 * into an OpenXR quad texture), starts another app's activity on it, and logs what arrives:
 *
 *   QUAD2D display=<id>                     the display id, for `input -d <id> tap x y`
 *   QUAD2D frame n=<count> hash=<h> luma=<mean>   once per second
 *
 * Extras: seconds (default 20), width, height, dpi; target (component, default
 * com.android.settings/.Settings) and launch=true to try starting it from this app.
 */
public class Quad2dActivity extends Activity {
    private static final String TAG = "QUAD2D";
    private static final int FLAG_PUBLIC = 1, FLAG_OWN_CONTENT_ONLY = 1 << 3;

    private ImageReader reader;
    private VirtualDisplay display;
    private HandlerThread thread;
    private int frames;
    private long lastReport;
    private long lastHash;
    private double lastLuma;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent in = getIntent();
        String target = in.getStringExtra("target");
        if (target == null) target = "com.android.settings/.Settings";
        int seconds = in.getIntExtra("seconds", 20);
        int w = in.getIntExtra("width", 1280), h = in.getIntExtra("height", 720);
        int dpi = in.getIntExtra("dpi", 240);

        thread = new HandlerThread("quad2d-frames");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3);
        reader.setOnImageAvailableListener(this::onFrame, handler);

        DisplayManager dm = (DisplayManager) getSystemService(Context.DISPLAY_SERVICE);
        display = dm.createVirtualDisplay("quad2d", w, h, dpi, reader.getSurface(),
                FLAG_PUBLIC | FLAG_OWN_CONTENT_ONLY);
        if (display == null) {
            Log.e(TAG, "createVirtualDisplay returned null");
            finish();
            return;
        }
        int id = display.getDisplay().getDisplayId();
        Log.i(TAG, "display=" + id);

        // An app cannot start another app's activity on its own display unless the display is
        // trusted (ADD_TRUSTED_DISPLAY, system apps only) or the activity allows embedding; the
        // spike lets the shell do it (`am start --display <id>`) and passes launch=true to try
        // from here.
        if (in.getBooleanExtra("launch", false)) try {
            ComponentName name = ComponentName.unflattenFromString(target);
            Intent launch = new Intent(Intent.ACTION_MAIN).setComponent(name)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
            ActivityOptions options = ActivityOptions.makeBasic();
            options.setLaunchDisplayId(id);
            startActivity(launch, options.toBundle());
            Log.i(TAG, "started " + target + " on display " + id);
        } catch (RuntimeException e) {
            Log.e(TAG, "cannot start " + target + " on the display: " + e);
        }
        handler.postDelayed(this::finish, seconds * 1000L);
    }

    private void onFrame(ImageReader r) {
        Image image = r.acquireLatestImage();
        if (image == null) return;
        try {
            frames++;
            Image.Plane plane = image.getPlanes()[0];
            ByteBuffer buf = plane.getBuffer();
            int stride = plane.getRowStride(), w = image.getWidth(), h = image.getHeight();
            long hash = 1125899906842597L, sum = 0;
            int samples = 0;
            for (int y = 0; y < h; y += 8) {
                for (int x = 0; x < w; x += 8) {
                    int o = y * stride + x * 4;
                    int rr = buf.get(o) & 0xff, gg = buf.get(o + 1) & 0xff, bb = buf.get(o + 2) & 0xff;
                    hash = 31 * hash + (rr << 16 | gg << 8 | bb);
                    sum += (rr * 3 + gg * 6 + bb) / 10;
                    samples++;
                }
            }
            lastHash = hash;
            lastLuma = sum / (double) samples;
            long now = System.currentTimeMillis();
            if (now - lastReport >= 1000) {
                lastReport = now;
                Log.i(TAG, "frame n=" + frames + " hash=" + Long.toHexString(lastHash)
                        + " luma=" + String.format("%.1f", lastLuma));
            }
        } finally {
            image.close();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (display != null) display.release();
        if (reader != null) reader.close();
        if (thread != null) thread.quitSafely();
        Log.i(TAG, "done frames=" + frames);
    }
}
