package dev.wgapps.settings;

import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** One app's choices, like a permission's: Default, a headset to pose as, or a model you type. */
public class ProfileActivity extends Activity {
    static final String EXTRA_PACKAGE = "package";

    private final ProfilesFile file = new ProfilesFile();
    /** The launch type the VR shell uses, in its own file: the host's apps-kind. */
    private final ProfilesFile kindsFile =
            new ProfilesFile(new java.io.File("/data/local/tmp/host_share/app-kinds.conf"));
    private final List<String> names = new ArrayList<>();
    private final List<RadioButton> radios = new ArrayList<>();
    private final List<String> kindNames = new ArrayList<>();
    private final List<RadioButton> kindRadios = new ArrayList<>();
    private String pkg;
    private LinearLayout customRow;
    private EditText customText;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        pkg = getIntent().getStringExtra(EXTRA_PACKAGE);
        if (pkg == null || !Profiles.validPackage(pkg)) {
            finish();
            return;
        }
        CharSequence label = pkg;
        android.graphics.drawable.Drawable icon = null;
        try {
            ApplicationInfo info = getPackageManager().getApplicationInfo(pkg, 0);
            label = info.loadLabel(getPackageManager());
            icon = info.loadIcon(getPackageManager());
        } catch (PackageManager.NameNotFoundException e) {
            // The app was removed while the list was open; the choices still work on the name.
        }
        setTitle("Device profile");
        if (getActionBar() != null) getActionBar().setDisplayHomeAsUpEnabled(true);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(0, dp(8), 0, dp(24));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setGravity(Gravity.CENTER_HORIZONTAL);
        header.setPadding(dp(24), dp(16), dp(24), dp(16));
        if (icon != null) {
            ImageView image = new ImageView(this);
            image.setImageDrawable(icon);
            header.addView(image, new LinearLayout.LayoutParams(dp(56), dp(56)));
        }
        TextView name = new TextView(this);
        name.setText(label);
        name.setGravity(Gravity.CENTER);
        name.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Large);
        header.addView(name);
        TextView explain = new TextView(this);
        explain.setText("What " + label + " is told about the device it runs on");
        explain.setGravity(Gravity.CENTER);
        explain.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Small);
        header.addView(explain);
        page.addView(header);

        page.addView(choice(names, radios, Profiles.DEFAULT, "The real device (" + Build.MODEL + ")", new Runnable() {
            @Override public void run() { choose(null); }
        }));
        for (final Profiles.Preset preset : Profiles.PRESETS) {
            page.addView(choice(names, radios, preset.name, preset.summary, new Runnable() {
                @Override public void run() { choose(preset); }
            }));
        }
        page.addView(choice(names, radios, Profiles.CUSTOM, "A model name you type", new Runnable() {
            @Override public void run() {
                customRow.setVisibility(View.VISIBLE);
                customText.requestFocus();
            }
        }));

        customRow = new LinearLayout(this);
        customRow.setOrientation(LinearLayout.HORIZONTAL);
        customRow.setGravity(Gravity.CENTER_VERTICAL);
        customRow.setPadding(dp(72), 0, dp(24), dp(8));
        customText = new EditText(this);
        customText.setSingleLine(true);
        customText.setInputType(InputType.TYPE_CLASS_TEXT);
        customText.setHint("Model");
        customRow.addView(customText, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button apply = new Button(this);
        apply.setText("Apply");
        apply.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { applyCustom(); }
        });
        customRow.addView(apply);
        page.addView(customRow);

        TextView kindHeader = new TextView(this);
        kindHeader.setText("Launch type in VR mode");
        kindHeader.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
        kindHeader.setPadding(dp(24), dp(24), dp(24), dp(4));
        page.addView(kindHeader);
        page.addView(choice(kindNames, kindRadios, "Detected", "Whether the app declares itself an OpenXR app", new Runnable() {
            @Override public void run() { chooseKind(null); }
        }));
        page.addView(choice(kindNames, kindRadios, "VR app", "Starts on its own, outside a window", new Runnable() {
            @Override public void run() { chooseKind(Kinds.XR); }
        }));
        page.addView(choice(kindNames, kindRadios, "Flat app", "Shown as a window in the VR shell", new Runnable() {
            @Override public void run() { chooseKind(Kinds.FLAT); }
        }));

        TextView note = new TextView(this);
        note.setText("Takes effect the next time the app starts. Close it first if it is running.");
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
        if (pkg != null) refresh();
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private View choice(List<String> into, List<RadioButton> radioInto, String name, String summary, final Runnable onSelect) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(24), dp(12), dp(24), dp(12));
        TypedValue background = new TypedValue();
        if (getTheme().resolveAttribute(android.R.attr.selectableItemBackground, background, true)) {
            row.setBackgroundResource(background.resourceId);
        }
        RadioButton radio = new RadioButton(this);
        radio.setClickable(false);
        radio.setFocusable(false);
        row.addView(radio);
        LinearLayout text = new LinearLayout(this);
        text.setOrientation(LinearLayout.VERTICAL);
        text.setPadding(dp(16), 0, 0, 0);
        TextView title = new TextView(this);
        title.setText(name);
        title.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
        text.addView(title);
        TextView sub = new TextView(this);
        sub.setText(summary);
        sub.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Small);
        text.addView(sub);
        row.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        row.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { onSelect.run(); }
        });
        into.add(name);
        radioInto.add(radio);
        return row;
    }

    /** null: back to the real device. */
    private void choose(Profiles.Preset preset) {
        Map<String, Map<String, String>> all = Profiles.byPackage(file.load());
        if (preset == null) Profiles.clear(all, pkg);
        else Profiles.setPreset(all, pkg, preset);
        save(all);
    }

    /** null: back to what the host detects. */
    private void chooseKind(String kind) {
        Map<String, String> all = Kinds.parse(kindsFile.load());
        Kinds.set(all, pkg, kind);
        try {
            kindsFile.save(Kinds.serialize(all));
        } catch (IOException e) {
            Toast.makeText(this, "Could not save: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        refresh();
    }

    private void applyCustom() {
        String model = customText.getText().toString().trim();
        Map<String, Map<String, String>> all = Profiles.byPackage(file.load());
        if (!Profiles.setCustom(all, pkg, model)) {
            Toast.makeText(this, "Use 1 to 91 letters, digits, spaces and . _ + ( ) / : -", Toast.LENGTH_LONG).show();
            return;
        }
        save(all);
    }

    private void save(Map<String, Map<String, String>> all) {
        try {
            file.save(Profiles.serialize(all));
        } catch (IOException e) {
            Toast.makeText(this, "Could not save: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        refresh();
    }

    private void refresh() {
        Map<String, String> keys = Profiles.byPackage(file.load()).get(pkg);
        String current = Profiles.current(keys);
        for (int i = 0; i < names.size(); i++) radios.get(i).setChecked(names.get(i).equals(current));
        boolean custom = Profiles.CUSTOM.equals(current);
        customRow.setVisibility(custom ? View.VISIBLE : View.GONE);
        if (custom && keys.get("model") != null) customText.setText(keys.get("model"));
        String kind = Kinds.parse(kindsFile.load()).get(pkg);
        String shown = Kinds.XR.equals(kind) ? "VR app" : Kinds.FLAT.equals(kind) ? "Flat app" : "Detected";
        for (int i = 0; i < kindNames.size(); i++) kindRadios.get(i).setChecked(kindNames.get(i).equals(shown));
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics());
    }
}
