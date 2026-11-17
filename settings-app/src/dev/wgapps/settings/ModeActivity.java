package dev.wgapps.settings;

import android.app.Activity;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.IOException;

/**
 * Settings > System > Steam Frame mode: Steam mode (the default) or VR mode, where a VR shell is the home.
 * It writes the one word to app-mode.conf in the shared folder; the host takes it over (and says no to
 * VR mode when the shell is not installed, which shows here as the choice snapping back).
 */
public class ModeActivity extends Activity {
    private final ProfilesFile file =
            new ProfilesFile(new File("/data/local/tmp/host_share/app-mode.conf"));
    private RadioButton steam;
    private RadioButton vr;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle("Steam Frame mode");
        if (getActionBar() != null) getActionBar().setDisplayHomeAsUpEnabled(true);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(0, dp(16), 0, dp(24));
        steam = new RadioButton(this);
        vr = new RadioButton(this);
        page.addView(row(steam, "Steam mode", "Every Android app is a Steam library entry; Android is one panel",
                Modes.STEAM));
        page.addView(row(vr, "VR mode", "A VR shell is the home: the library, and apps as windows in the headset",
                Modes.VR));
        TextView note = new TextView(this);
        note.setText("Takes effect the next time Android starts. VR mode needs the VR shell installed on the "
                + "host; without it this stays on Steam mode.");
        note.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Small);
        note.setPadding(dp(24), dp(16), dp(24), 0);
        page.addView(note);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(page);
        setContentView(scroll);
    }

    @Override
    protected void onResume() {
        super.onResume();
        String mode = Modes.parse(file.load());
        steam.setChecked(Modes.STEAM.equals(mode));
        vr.setChecked(Modes.VR.equals(mode));
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private View row(RadioButton radio, String title, String summary, final String mode) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(24), dp(12), dp(24), dp(12));
        TypedValue background = new TypedValue();
        if (getTheme().resolveAttribute(android.R.attr.selectableItemBackground, background, true)) {
            row.setBackgroundResource(background.resourceId);
        }
        radio.setClickable(false);
        radio.setFocusable(false);
        row.addView(radio);
        LinearLayout text = new LinearLayout(this);
        text.setOrientation(LinearLayout.VERTICAL);
        text.setPadding(dp(16), 0, 0, 0);
        TextView name = new TextView(this);
        name.setText(title);
        name.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
        text.addView(name);
        TextView sub = new TextView(this);
        sub.setText(summary);
        sub.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Small);
        text.addView(sub);
        row.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        row.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { choose(mode); }
        });
        return row;
    }

    private void choose(String mode) {
        try {
            file.save(Modes.serialize(mode));
        } catch (IOException e) {
            Toast.makeText(this, "Could not save: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        steam.setChecked(Modes.STEAM.equals(mode));
        vr.setChecked(Modes.VR.equals(mode));
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics());
    }
}
