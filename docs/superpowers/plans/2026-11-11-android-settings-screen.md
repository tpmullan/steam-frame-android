# Device profile screen in Android's Settings: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** In Android's own Settings, a screen like the location-permission one: a list of apps, and tapping one gives radio choices (Default, Meta Quest 3, …, Custom) that set that app's device profile (the overrides from `docs/superpowers/plans/2026-11-10-per-app-overrides.md`).

**Architecture:** A small system app (`dev.wgapps.settings`, installed as `/system/priv-app` through the launcher's bind mounts, because Settings lists injected entries from system apps only; verified on the Frame: a user-installed copy is not listed, the priv-app copy shows in Settings > System) provides the screens. It reads and writes one file in the folder shared with the host, `/data/local/tmp/host_share/device-profiles.conf`, in `apps.conf`'s format. A host helper `bin/wgapps-profiles` notices a changed file and runs `wgapps app import`, which validates it, makes it the new `apps.conf`, regenerates the per-package files and sets the live `wrap.` properties. The host mirrors `apps.conf` back to the same file after every change, so the screen always shows the truth.

**Tech Stack:** Java (framework APIs only, no AndroidX) built by hand with the SDK's `aapt2`/`d8`/`apksigner` (`tools/build-settings-app.sh`), bash (`bin/wgapps`), Python (`bin/wgapps-profiles`, `unittest`).

**Spec:** the user's request: "implement the plan to support per app settings for device in Android settings" and "something like the location permission grant screen".

## Global Constraints

- No privileged permissions (no allowlist file, nothing that needs signing with the platform key); the app only needs `<queries>` for launcher apps.
- The shared folder `$SHARE` is made mode 0777 at start; the app creates the file with `setReadable(true, false)` so the host can read it; the host writes it mode 0644 and may replace app-owned files because it owns the folder.
- Everything the host accepts goes through the existing validators (`app_valid_package`, `app_valid_key`, `app_valid_value`); an invalid line is dropped, never partly applied.
- The helper imports only when the shared file differs from `apps.conf` on two polls in a row, one second apart (a host-side change updates `apps.conf` a moment before the mirror).
- (Built as planned; verified on the Frame 2026-11-11 with screenshots of every screen: list, choices, refused custom name, and the tap path from Settings > System. Android's screen is 1920x1080 while screenshots are 1280x720: taps need coordinates x1.5.)
- Presets set `model`, `manufacturer`, `brand` and `device` (values only from the permitted set: letters, digits, space and `. _ + ( ) / : -`): Meta Quest 3 (`Quest 3`/`Oculus`/`oculus`/`eureka`), Meta Quest 3S (`Quest 3S`/`Oculus`/`oculus`/`sepulcher`), Meta Quest Pro (`Quest Pro`/`Oculus`/`oculus`/`seacliff`), Meta Quest 2 (`Quest 2`/`Oculus`/`oculus`/`hollywood`), Pico 4 (`A8110`/`PICO`/`PICO`), Pico 4 Ultra (`A9210`/`PICO`/`PICO`); plus Default (no lines) and Custom (a model typed by the user).
- The APK is optional, like the other add-ons: nothing is mounted when `$BASE/lib/WgappsSettings.apk` is absent. It is not added to the release file list (`sfa_release.py` forbids `.apk`); building and shipping it is a follow-up decision.
- Shell passes `shellcheck -x` and `shfmt -d`; Python passes `ruff@0.13.0`.

## Review Focus

- A change made on the host (`app set`) shows on the screen, and one made on the screen reaches the host, neither overwriting the other mid-change (Task 1 tests the debounce and the mirror).
- A garbled or hostile shared file (invalid lines, bad characters, huge, binary) changes nothing outside the valid lines and never crashes the helper (Task 1).
- The app list shows only apps a user can open, and an app with no launcher entry can still be reached through `apps.conf` (Task 2 test of the parser keeps unknown lines).
- Choosing Default removes only that package's lines; other packages' lines stay (Task 2).
- Custom model text that the host would reject is refused on the screen before it is saved (Task 2).
- The screen works with no file yet and with the container's first boot (Task 3).

---

### Task 1: Host side

**Files:**
- Modify: `bin/wgapps` (`cmd_app import`, `export_profiles`, `mount_settings_app`, `start_helpers`/`stop_helpers`, `cmd_start` mkdir/chmod of `$SHARE`, `usage`)
- Create: `bin/wgapps-profiles`, `tests/test_profiles.py`; extend `tests/test_apps.py`

**Interfaces:**
- Produces: `wgapps app import <file>` (validate, replace `apps.conf`, regenerate, apply live to changed packages, mirror); `export_profiles` (copies `apps.conf` to `$SHARE/device-profiles.conf`, mode 0644, atomically); `mount_settings_app` (binds `$BASE/lib/WgappsSettings.apk` at `/system/priv-app/WgappsSettings/WgappsSettings.apk` ro); `bin/wgapps-profiles` (polls `$WGAPPS_SHARE/device-profiles.conf` against `$WGAPPS_BASE/apps.conf`; runs `$WGAPPS_BIN app import <file>` after two consecutive differing polls).

- [x] **Step 1: Tests** in `tests/test_apps.py`: `test_import_replaces_apps_conf_with_the_valid_lines` (a file with two valid, one bad-key, one bad-value, one garbage, one empty line → only the two valid lines kept, mirror equals `apps.conf`); `test_import_of_an_empty_file_clears_everything`; `test_import_keeps_only_the_last_line_per_package_and_key`; `test_import_ignores_files_over_64_KiB_and_binary_content` (apps.conf unchanged); `test_set_and_unset_mirror_to_the_shared_file`; `test_mirror_is_mode_0644_and_not_a_partial_file`. In `tests/test_profiles.py`: `test_no_import_on_one_differing_poll`, `test_import_after_two_differing_polls`, `test_no_import_when_equal`, `test_a_failed_import_does_not_stop_the_loop` (helper function `poll(state)` is separate from the loop so it is testable); the module is loaded with `helpers.load("wgapps-profiles")`.
- [x] **Step 2: Run, expect failures.** `python3 -m unittest discover -s tests`
- [x] **Step 3: Implement** `cmd_app import`, `export_profiles`, call `export_profiles` after `app_conf_rewrite` and in `cmd_start`, `mount_settings_app` in `cmd_start` next to `mount_app_props`, `mkdir -p "$SHARE"; chmod 0777 "$SHARE"`, `wgapps-profiles` in `start_helpers`/`stop_helpers` (it needs `WGAPPS_BIN`, `WGAPPS_BASE`, `WGAPPS_SHARE` in its environment). `bin/wgapps-profiles` is a ~60 line Python script in the style of `wgapps-battery`.
- [x] **Step 4: Run the whole suite and the linters.**

### Task 2: The Android app

**Files:**
- Create: `settings-app/AndroidManifest.xml`, `settings-app/src/dev/wgapps/settings/{Profiles,ProfilesFile,AppListActivity,ProfileActivity}.java`, `settings-app/test/ProfilesTest.java`, `settings-app/res/…`, `tools/build-settings-app.sh`

**Interfaces:**
- `Profiles`: pure Java, no Android types. `static List<String> parse(String text)` (lines), `static Map<String,Map<String,String>> byPackage(String text)`, `static String serialize(Map<String,Map<String,String>>)` (package order stable, keys in `model, manufacturer, brand, device` order), `static final Preset[] PRESETS` (name, summary, key→value), `static String current(Map<String,String> keys)` returns a preset name, `"Default"` for none, or `"Custom"`, `static boolean validValue(String)` (the host's rule), `static boolean validPackage(String)`.
- `ProfilesFile`: `load()` returns the text or "", `save(String)` writes `device-profiles.conf.tmp` then renames, `setReadable(true,false)`.

- [x] **Step 1: Write `ProfilesTest.java`** (plain `main`, `assert`-style checks, run with `java -ea`): parse/serialize round trip; unknown lines survive; `current` recognises each preset and Custom; `validValue` accepts `Quest 3`, `a.b_c+(d)/e:f-g`, rejects empty, 92 characters, quotes, `;`, `$`, newline, leading/trailing space; `validPackage` as the host.
- [x] **Step 2: Run it, expect compile failure.**
- [x] **Step 3: Implement `Profiles`, `ProfilesFile`; run the test, expect pass.**
- [x] **Step 4: Screens.** `AppListActivity` (theme `@android:style/Theme.DeviceDefault.Settings`, a `ListView` of launcher apps sorted by label: icon, label, summary = current profile; refreshes `onResume`); `ProfileActivity` (header icon + label + package; radio rows for Default, each preset, Custom with an `EditText` row; "applies the next time the app starts" footnote). Manifest: the injection filter and metadata as in the spike (`com.android.settings.action.EXTRA_SETTINGS`, category `com.android.settings.category.ia.system`, title and summary), `<queries>` for `MAIN`/`LAUNCHER`.
- [x] **Step 5: `tools/build-settings-app.sh`**: runs the test, `aapt2 link`, `javac --release 8`, `d8`, zip, `zipalign`, `apksigner` with the debug keystore, output `<out>/WgappsSettings.apk`; refuses to run without the SDK (`ANDROID_HOME` or `~/Library/Android/sdk`).

### Task 3: On the Frame

- [x] **Step 1: Deploy** launcher, helper and APK; remove the spike (`local-overrides/system/priv-app/WgappsSettings`); restart Android.
- [x] **Step 2: Screens.** Open Settings > System > Device profile per app; screenshots of the list and of an app's choices.
- [x] **Step 3: Choose Meta Quest 3 for Wolvic on the screen** (input events in the container), see `wgapps app list` change on the host and Wolvic log `Meta Quest 3` after a restart of the app; choose Default and see it undone.
- [x] **Step 4: Host change shows on the screen** (`app set`, then the list's summary).
- [x] **Step 5: README, memory.** Leave the Frame with no override set.
