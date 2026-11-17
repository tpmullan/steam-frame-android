package dev.wgapps.shell;

import android.app.NativeActivity;
import android.graphics.Bitmap;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * V1: the shell in VR. The OpenXR session and the quad are native (native/shell.c, loaded as
 * "wgshell" through the manifest); the picture on the quad is drawn here, where text is easy, and
 * handed over by {@link #gridPixels()} whenever the native side asks.
 */
public class VrShellActivity extends NativeActivity {
    public static final int WIDTH = 1920;
    public static final int HEIGHT = 1080;

    // Look: Android's own launcher (a grid of icons, a dock along the bottom), Steam's library (the
    // things you play first, then everything), Quest-style panels (rounded, dark, one accent).
    private static final int BG = Color.rgb(14, 16, 22);
    private static final int PANEL = Color.rgb(30, 33, 42);
    private static final int TILE = Color.rgb(44, 48, 60);
    private static final int TILE_VR = Color.rgb(38, 66, 112);
    private static final int ACCENT = Color.rgb(26, 159, 255); // Steam's blue
    private static final int TEXT = Color.rgb(235, 238, 245);
    private static final int MUTED = Color.rgb(150, 156, 170);
    private static final String[] DOCK = {
        "com.android.vending", "com.android.chrome", "com.plexapp.android", "com.android.settings"
    };

    private static final int MARGIN = 64;
    private static final int HEADER = 112;
    private static final int DOCK_HEIGHT = 128;
    private static final int COLUMNS = 8;
    private static final int TILE_SIZE = 180;
    private static final int LABEL_HEIGHT = 40;

    private static Context context;
    private static final Hits hits = new Hits();
    private static volatile String hover;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        context = getApplicationContext();
    }

    /** ARGB pixels of the shell, WIDTH x HEIGHT; called from the native thread. */
    public static int[] gridPixels() {
        List<Catalog.Entry> apps = Catalog.parse(read(new File(Catalog.DEFAULT_PATH)));
        Bitmap bitmap = Bitmap.createBitmap(WIDTH, HEIGHT, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(BG);
        hits.clear();
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        drawHeader(canvas, paint, apps.size());
        List<Catalog.Entry> vr = new ArrayList<>(), flat = new ArrayList<>();
        for (Catalog.Entry app : apps) (app.xr ? vr : flat).add(app);
        int y = HEADER + 16;
        y = drawSection(canvas, paint, "VR apps", vr, y);
        drawSection(canvas, paint, "Apps", flat, y + 8);
        drawDock(canvas, paint, apps);

        int[] pixels = new int[WIDTH * HEIGHT];
        bitmap.getPixels(pixels, 0, WIDTH, 0, 0, WIDTH, HEIGHT);
        bitmap.recycle();
        return pixels;
    }

    private static void drawHeader(Canvas canvas, Paint paint, int count) {
        paint.setTypeface(Typeface.DEFAULT_BOLD);
        paint.setTextAlign(Paint.Align.LEFT);
        paint.setColor(TEXT);
        paint.setTextSize(44);
        canvas.drawText("Library", MARGIN, 76, paint);
        // Tabs: the first is the active one (a pointer selects the others in a later step).
        String[] tabs = {"All", "VR", "Flat"};
        float x = 400;
        for (int i = 0; i < tabs.length; i++) {
            paint.setTextSize(30);
            float w = paint.measureText(tabs[i]) + 56;
            paint.setColor(i == 0 ? ACCENT : PANEL);
            canvas.drawRoundRect(new RectF(x, 32, x + w, 88), 28, 28, paint);
            paint.setColor(i == 0 ? Color.WHITE : MUTED);
            paint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(tabs[i], x + w / 2, 70, paint);
            paint.setTextAlign(Paint.Align.LEFT);
            x += w + 16;
        }
        paint.setTextAlign(Paint.Align.RIGHT);
        paint.setColor(TEXT);
        paint.setTextSize(36);
        canvas.drawText(new SimpleDateFormat("h:mm a", Locale.US).format(new Date()), WIDTH - MARGIN, 72, paint);
        paint.setColor(MUTED);
        paint.setTextSize(26);
        canvas.drawText(count + " apps", WIDTH - MARGIN - 190, 72, paint);
        paint.setTextAlign(Paint.Align.LEFT);
    }

    /** A titled grid of tiles from Y down; returns the Y below it. */
    private static int drawSection(Canvas canvas, Paint paint, String title, List<Catalog.Entry> apps, int y) {
        if (apps.isEmpty()) return y;
        paint.setTypeface(Typeface.DEFAULT_BOLD);
        paint.setColor(MUTED);
        paint.setTextSize(28);
        paint.setTextAlign(Paint.Align.LEFT);
        canvas.drawText(title, MARGIN, y + 30, paint);
        y += 48;
        int gap = (WIDTH - MARGIN * 2 - COLUMNS * TILE_SIZE) / (COLUMNS - 1);
        int rowHeight = TILE_SIZE + LABEL_HEIGHT + 12;
        for (int i = 0; i < apps.size(); i++) {
            int row = i / COLUMNS;
            if (y + (row + 1) * rowHeight > HEIGHT - DOCK_HEIGHT - 24) break;
            int left = MARGIN + (i % COLUMNS) * (TILE_SIZE + gap);
            int top = y + row * rowHeight;
            drawTile(canvas, paint, apps.get(i), left, top);
        }
        int rows = (apps.size() + COLUMNS - 1) / COLUMNS;
        return y + rows * rowHeight;
    }

    private static void drawTile(Canvas canvas, Paint paint, Catalog.Entry app, int left, int top) {
        String key = app.component();
        hits.add(left, top, left + TILE_SIZE, top + TILE_SIZE + LABEL_HEIGHT, key);
        paint.setColor(app.xr ? TILE_VR : TILE);
        canvas.drawRoundRect(new RectF(left, top, left + TILE_SIZE, top + TILE_SIZE), 28, 28, paint);
        if (key.equals(hover)) {
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(6);
            paint.setColor(ACCENT);
            canvas.drawRoundRect(new RectF(left, top, left + TILE_SIZE, top + TILE_SIZE), 28, 28, paint);
            paint.setStyle(Paint.Style.FILL);
        }
        drawIcon(canvas, paint, app, left + (TILE_SIZE - 96) / 2, top + (TILE_SIZE - 96) / 2 - 4, 96);
        if (app.xr) {
            paint.setColor(ACCENT);
            canvas.drawRoundRect(new RectF(left + TILE_SIZE - 62, top + 10, left + TILE_SIZE - 10, top + 40), 15, 15, paint);
            paint.setColor(Color.WHITE);
            paint.setTextSize(20);
            paint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText("VR", left + TILE_SIZE - 36, top + 32, paint);
        }
        paint.setTypeface(Typeface.DEFAULT);
        paint.setColor(TEXT);
        paint.setTextSize(25);
        paint.setTextAlign(Paint.Align.CENTER);
        canvas.drawText(fit(app.label, paint, TILE_SIZE + 8), left + TILE_SIZE / 2f, top + TILE_SIZE + 32, paint);
        paint.setTypeface(Typeface.DEFAULT_BOLD);
        paint.setTextAlign(Paint.Align.LEFT);
    }

    /** The app's own icon; a rounded letter when it cannot be loaded. */
    private static void drawIcon(Canvas canvas, Paint paint, Catalog.Entry app, int x, int y, int size) {
        Drawable icon = null;
        if (context != null) {
            try {
                icon = context.getPackageManager().getApplicationIcon(app.packageName);
            } catch (PackageManager.NameNotFoundException | RuntimeException e) {
                icon = null;
            }
        }
        if (icon != null) {
            icon.setBounds(x, y, x + size, y + size);
            icon.draw(canvas);
            return;
        }
        paint.setColor(ACCENT);
        canvas.drawRoundRect(new RectF(x, y, x + size, y + size), size / 4f, size / 4f, paint);
        paint.setColor(Color.WHITE);
        paint.setTextSize(size / 2f);
        paint.setTextAlign(Paint.Align.CENTER);
        canvas.drawText(app.label.substring(0, 1).toUpperCase(Locale.ROOT), x + size / 2f, y + size * 0.68f, paint);
    }

    /** A dock along the bottom, like Android's hotseat: a few favorites, centered. */
    private static void drawDock(Canvas canvas, Paint paint, List<Catalog.Entry> apps) {
        List<Catalog.Entry> favorites = new ArrayList<>();
        for (String pkg : DOCK)
            for (Catalog.Entry app : apps)
                if (app.packageName.equals(pkg)) favorites.add(app);
        if (favorites.isEmpty()) return;
        int slot = 104, gap = 28;
        int width = favorites.size() * slot + (favorites.size() - 1) * gap + 72;
        int left = (WIDTH - width) / 2, top = HEIGHT - DOCK_HEIGHT;
        paint.setColor(PANEL);
        canvas.drawRoundRect(new RectF(left, top, left + width, top + 104), 52, 52, paint);
        for (int i = 0; i < favorites.size(); i++) {
            Catalog.Entry app = favorites.get(i);
            int x = left + 36 + i * (slot + gap) + 4;
            hits.add(x - 8, top + 4, x + 88, top + 100, app.component());
            if (app.component().equals(hover)) {
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(6);
                paint.setColor(ACCENT);
                canvas.drawCircle(x + 40, top + 52, 46, paint);
                paint.setStyle(Paint.Style.FILL);
            }
            drawIcon(canvas, paint, app, x, top + 12, 80);
        }
    }

    /** Called from the native thread with the pointer's pixel (or -1, -1): 1 when the hover changed. */
    public static int onHover(int x, int y) {
        String now = x < 0 ? null : hits.at(x, y);
        boolean changed = now == null ? hover != null : !now.equals(hover);
        hover = now;
        return changed ? 1 : 0;
    }

    /** The trigger was pressed with the pointer at (x, y): start what is there. */
    public static void onClick(int x, int y) {
        String component = hits.at(x, y);
        if (component == null || context == null) return;
        Intent intent = new Intent(Intent.ACTION_MAIN)
                .setComponent(ComponentName.unflattenFromString(component))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
            android.util.Log.i("WGSHELL", "launch " + component);
        } catch (RuntimeException e) {
            android.util.Log.e("WGSHELL", "cannot start " + component + ": " + e);
        }
    }

    private static String fit(String label, Paint paint, int width) {
        String s = label;
        while (s.length() > 1 && paint.measureText(s) > width) s = s.substring(0, s.length() - 1);
        return s.length() < label.length() ? s + "…" : s;
    }

    private static String read(File file) {
        try (FileInputStream in = new FileInputStream(file)) {
            byte[] bytes = new byte[(int) Math.min(file.length(), 1 << 20)];
            int n = in.read(bytes);
            return n <= 0 ? "" : new String(bytes, 0, n, StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }
}
