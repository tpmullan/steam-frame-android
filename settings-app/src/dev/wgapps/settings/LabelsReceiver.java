package dev.wgapps.settings;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Writes the names of the launchable apps to app-labels.conf in the shared folder, for the host's app
 * catalog (wgapps apps list): at boot, and whenever the host sends this receiver a broadcast.
 */
public final class LabelsReceiver extends BroadcastReceiver {
    private static final String TAG = "wgapps-labels";
    static final String PATH = "/data/local/tmp/host_share/app-labels.conf";

    @Override
    public void onReceive(Context context, Intent intent) {
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                write(context.getApplicationContext());
            } catch (IOException | RuntimeException e) {
                Log.w(TAG, "could not write " + PATH, e);
            } finally {
                pending.finish();
            }
        }).start();
    }

    static void write(Context context) throws IOException {
        PackageManager packages = context.getPackageManager();
        Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<String[]> rows = new ArrayList<>();
        for (ResolveInfo info : packages.queryIntentActivities(launcher, 0)) {
            rows.add(new String[] {info.activityInfo.packageName, String.valueOf(info.loadLabel(packages))});
        }
        new ProfilesFile(new File(PATH)).save(Labels.serialize(rows));
    }
}
