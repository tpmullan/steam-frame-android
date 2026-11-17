package dev.wgapps.shell;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.GridLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * V1 skeleton: the app grid. A flat window for now; the OpenXR scene (controller ray, quad
 * layers) replaces the drawing, not the catalog or the launching. Logs "WGSHELL ready n=<apps>"
 * once it shows, which `wgapps` reads to decide whether the shell started.
 */
public class ShellActivity extends Activity {
    private static final String TAG = "WGSHELL";
    private static final int COLUMNS = 4;

    private GridLayout grid;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.rgb(16, 18, 24));
        GridLayout root = new GridLayout(this);
        root.setColumnCount(1);
        root.setPadding(48, 48, 48, 48);
        status = new TextView(this);
        status.setTextColor(Color.LTGRAY);
        status.setTextSize(18);
        root.addView(status);
        grid = new GridLayout(this);
        grid.setColumnCount(COLUMNS);
        root.addView(grid);
        scroll.addView(root);
        setContentView(scroll);
    }

    @Override
    protected void onResume() {
        super.onResume();
        List<Catalog.Entry> apps = Catalog.parse(read(new File(Catalog.DEFAULT_PATH)));
        grid.removeAllViews();
        for (final Catalog.Entry app : apps) {
            Button button = new Button(this);
            button.setText(app.xr ? app.label + "  (VR)" : app.label);
            button.setAllCaps(false);
            button.setGravity(Gravity.CENTER);
            button.setTextSize(18);
            GridLayout.LayoutParams size = new GridLayout.LayoutParams();
            size.width = 420;
            size.height = 120;
            size.setMargins(12, 12, 12, 12);
            button.setLayoutParams(size);
            button.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    launch(app);
                }
            });
            grid.addView(button);
        }
        status.setText(apps.isEmpty()
                ? "No apps yet: run `wgapps apps push` on the Frame."
                : apps.size() + " apps");
        Log.i(TAG, "ready n=" + apps.size());
    }

    private void launch(Catalog.Entry app) {
        Intent intent = new Intent(Intent.ACTION_MAIN)
                .setComponent(ComponentName.unflattenFromString(app.component()))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
        } catch (RuntimeException e) {
            Log.e(TAG, "cannot start " + app.component() + ": " + e);
        }
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
