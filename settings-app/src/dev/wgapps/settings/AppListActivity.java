package dev.wgapps.settings;

import android.app.ListActivity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Settings > System > Device profile per app: every app you can open, and the profile it sees. */
public class AppListActivity extends ListActivity {
    private static final class App {
        final String pkg;
        final CharSequence label;
        final Drawable icon;

        App(String pkg, CharSequence label, Drawable icon) {
            this.pkg = pkg;
            this.label = label;
            this.icon = icon;
        }
    }

    private final ProfilesFile file = new ProfilesFile();
    private final List<App> apps = new ArrayList<>();
    private Map<String, Map<String, String>> profiles;
    private final BaseAdapter adapter = new BaseAdapter() {
        @Override public int getCount() { return apps.size(); }
        @Override public Object getItem(int position) { return apps.get(position); }
        @Override public long getItemId(int position) { return position; }

        @Override public View getView(int position, View convert, ViewGroup parent) {
            App app = apps.get(position);
            Context context = AppListActivity.this;
            LinearLayout row = new LinearLayout(context);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(24), dp(12), dp(24), dp(12));
            ImageView icon = new ImageView(context);
            icon.setImageDrawable(app.icon);
            row.addView(icon, new LinearLayout.LayoutParams(dp(40), dp(40)));
            LinearLayout text = new LinearLayout(context);
            text.setOrientation(LinearLayout.VERTICAL);
            text.setPadding(dp(24), 0, 0, 0);
            TextView title = new TextView(context);
            title.setText(app.label);
            title.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
            text.addView(title);
            TextView summary = new TextView(context);
            summary.setText(summary(app.pkg));
            summary.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Small);
            summary.setTextColor(attrColor(android.R.attr.textColorSecondary));
            text.addView(summary);
            row.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            return row;
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle("Device profile per app");
        if (getActionBar() != null) getActionBar().setDisplayHomeAsUpEnabled(true);
        ListView list = getListView();
        list.setDivider(null);
        setListAdapter(adapter);
    }

    @Override
    protected void onResume() {
        super.onResume();
        load();
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    protected void onListItemClick(ListView list, View view, int position, long id) {
        Intent intent = new Intent(this, ProfileActivity.class);
        intent.putExtra(ProfileActivity.EXTRA_PACKAGE, apps.get(position).pkg);
        startActivity(intent);
    }

    private void load() {
        PackageManager pm = getPackageManager();
        Intent main = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        Set<String> seen = new HashSet<>();
        apps.clear();
        for (ResolveInfo info : pm.queryIntentActivities(main, 0)) {
            String pkg = info.activityInfo.packageName;
            if (seen.add(pkg)) apps.add(new App(pkg, info.loadLabel(pm), info.loadIcon(pm)));
        }
        Collections.sort(apps, new Comparator<App>() {
            @Override public int compare(App a, App b) {
                return a.label.toString().compareToIgnoreCase(b.label.toString());
            }
        });
        profiles = Profiles.byPackage(file.load());
        adapter.notifyDataSetChanged();
    }

    private String summary(String pkg) {
        Map<String, String> keys = profiles.get(pkg);
        String current = Profiles.current(keys);
        if (Profiles.CUSTOM.equals(current)) return "Custom: " + keys.get("model");
        return current;
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics());
    }

    private int attrColor(int attr) {
        TypedValue value = new TypedValue();
        getTheme().resolveAttribute(attr, value, true);
        return getResources().getColor(value.resourceId, getTheme());
    }
}
