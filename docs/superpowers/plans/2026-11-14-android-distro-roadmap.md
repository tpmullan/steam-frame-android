# Android on the Frame as a distro: Steam mode and optional VR mode

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Android container that can be used two ways, chosen by the user: **Steam mode** (every Android app is a Steam library entry; Android shows as one flat panel with its own window manager) and **VR mode** (a native OpenXR shell app in the container: library, 2D app windows in 3D, and an optional 3D home). Steam mode is the default and must keep working whatever happens to VR mode.

**Architecture:** Both modes share the existing `wgapps` container, per-app device profiles and Settings screen. Steam mode adds an app catalog, a Steam shortcut sync, and launch/quit behaviour that attaches to the running container (no restart). VR mode is a separate APK (`vr-shell/`) started by `wgapps` when the mode is `vr`; it uses the OpenXR plumbing already in `xr-layer/` and shows the 3D home as an optional background of the same app. Everything in VR mode that depends on unknowns (2D-in-3D compositing, OpenXR session handoff, passthrough) starts as a written spike whose finding decides the later tasks.

**Tech Stack:** bash (`bin/wgapps`), Python (`bin/steam-shortcuts.py`, helpers, `unittest`), Android Java (framework APIs, like `settings-app/`), native OpenXR on Android (stack chosen by the spike: native or Godot), the existing `xr-layer/` API layer.

**Spec:** the user's requests in this session: "tighter integration in steam or a launcher like quest with better desktop management", "our setup copying lepton with features", "a 3d VR native Android launcher", "I also want the 3d home as optional so we can use apps in a tight steam mode or full VR Android". Research notes: Lepton (`compat_tool/`, MIT; rootfs GPL-3.0), QuestHome (`PROPOSAL.md`, GPL-3.0), Lightning Launcher (GPL-3.0), frame-control field notes.

## Global Constraints

- One shared container (no per-app containers); apps are not isolated from each other. Users wanting isolation use Lepton.
- Steam mode works with no VR shell installed, and the VR shell is optional: nothing is mounted or started for it when `$BASE/lib/WgappsShell.apk` is absent (same rule as `WgappsSettings.apk`).
- Mode setting: `wgapps mode steam|vr` (default `steam`), stored in `$BASE/mode`; `update` and `rollback` leave it alone. The 3D home is a setting of VR mode (`home=on|off`), never a separate mode.
- Android multi-window uses `persist.waydroid.multi_windows=true` (verified on the Frame 2026-11-14: tasks become `mode=freeform`, windows have caption buttons, all drawn into the one gamescope panel). It is a launcher setting `windows=floating|single`, default `single`, applied at container start.
- Per-app Steam panels are not possible with this container (every Android window shares one Wayland client, and gamescope maps a client to a Steam app by process ancestry); no task may depend on them.
- `steam-shortcuts.py` refuses to write while Steam runs (it would overwrite `shortcuts.vdf`). Task S1 decides how sync works under that rule; no task may edit `shortcuts.vdf` while Steam is running.
- Anything copied from Lepton keeps its licence header and is listed in `NOTICE.md` (compat tool MIT; GPL-3.0 files stay GPL-3.0). Cover art is fetched at runtime, never bundled.
- Shell passes `shellcheck -x` and `shfmt -d`; Python passes `ruff@0.13.0` check and format; the full suite `python3 -m unittest discover -s tests` stays green.
- Nothing is committed until the user asks. The Frame is left in a known state after every on-device task (no leftover test props, files or processes).

## Review Focus

- A launch from Steam while Android is already running starts that app and does not restart the container or kill other apps (Task 3).
- Quitting a Steam entry stops only that app, and Steam's "running" state follows the app's process, including when the user quits the app inside Android (Task 3).
- The catalog survives apps with no launcher label, no icon, duplicate labels, and packages installed or removed while `wgapps` runs (Task 1).
- Sync never deletes or renames a shortcut the user made by hand (Tasks 2 and S1).
- Switching mode never leaves both a flat launcher and the VR shell fighting for the display, and a broken VR shell falls back to Steam mode (Task 4).
- The 3D home off or its assets missing leaves a working shell (Tasks V1, V3).

## File Structure

- `bin/wgapps`: new `cmd_apps`, `cmd_mode`, launch/quit changes in `cmd_steam`, window-mode prop in `write_props`, mode handling in `cmd_start`.
- `bin/steam-shortcuts.py`: sync support (add/remove by tag, by package).
- `bin/wgapps-appwatch` (new, Python): exit watcher for the running app.
- `tests/test_catalog.py`, `tests/test_mode.py`, `tests/test_shortcuts.py` (extend), `tests/test_appwatch.py`.
- `vr-shell/` (new, Phase 2+), `docs/superpowers/spikes/` (spike findings), `NOTICE.md`.

---

## Phase 0: Spikes (no product code; each ends with a written finding)

Each spike writes `docs/superpowers/spikes/<id>.md` with: question, what was run, result, the decision it makes, and how the Frame was restored. A spike whose answer is "not possible" changes the later tasks before they start.

### Task S1: Add and remove Steam shortcuts while Steam runs

- [x] **Step 1:** List the candidate mechanisms and try each on the Frame, safest first: a Steam URL (`steam://addnonsteamgame/...`), Steam's web UI debug port (CEF remote debugging) calling the client's shortcut API, SteamOS 0.5.6's right-click APK feature, and closing Steam, writing `shortcuts.vdf`, restarting it. Record for each: works or not, needs Steam restart, leaves the entry usable, survives a Steam restart.
- [x] **Step 2:** Decide the sync mechanism and record it. Fallback if none works live: sync happens when Steam is not running (at `wgapps install`/`update` and on a `wgapps apps sync --restart-steam` the user runs deliberately).
- [x] **Step 3:** Delete the test shortcuts, confirm `steam-shortcuts.py list` shows only the original three.
- Finding: `docs/superpowers/spikes/S1-live-shortcuts.md` (live mode through Steam's debug port; Task 2 uses it).

### Task S2: Launch semantics with several entries

- [x] **Step 1:** With Android running under the "Android" entry, launch the "Plex" entry. Record: does `cmd_steam` restart the container (today it does), what `GAMESCOPE_FOCUSED_APP` and the `valve.steam.desktopgame.<id>` overlays show, which panel holds the window, and what Steam shows as running.
- [x] **Step 2:** Try the candidate behaviour: the second entry's `wgapps steam <pkg>` skips the restart, runs `am start`, and waits on the package's process while the first reaper keeps owning the panel. Record whether quitting either entry from Steam does the right thing.
- [x] **Step 3:** Decide the behaviour for Task 3 (and the owner of the panel: "Android" entry always, or the most recent entry).
- Finding: `docs/superpowers/spikes/S2-launch-semantics.md` (attach works; the first entry owns the panel).

### Task S3: Session handoff and panel coexistence (done; see `spikes/S3-S4-S5-partial.md`)

- [x] **Step 1:** With the Android panel visible, start `hello_xr` (GLES) in the container. Record whether the panel and the OpenXR scene show together (stereo screenshot via the existing vrshot tooling), and where input goes. *Answered: the Android panel is a separate SteamVR overlay that stays visible next to a running OpenXR app that has not taken focus; with the app FOCUSED the panel is not in the scene screenshot (`spikes/S3-S4-S5-partial.md`, S3 and its update).*
- [x] **Step 2:** Start hello_xr, end it, start Wolvic, end it. Record session state changes (`SessionStateChanged` in logcat), the time between apps, and any dashboard or black frames. *Answered: IDLE, READY, SYNCHRONIZED, VISIBLE, FOCUSED; about 3 s between ending one app and the next session being READY; no black frames or stuck dashboard.*
- [x] **Step 3:** Decide: can the VR shell be one session that ends when it launches an XR app and is started again afterwards, and does the flat panel need hiding while the shell is up. *Decided: the shell is one session that ends when it launches an XR app and starts again afterwards; the flat panel returns on its own.*

### Task S4: 2D app into a 3D quad (done 2026-11-15; the quad upload is the engine plan's R4 step 2)

- [x] **Step 1:** Minimal native test app (separate from the shell, `spikes/quad2d/`): create a `VirtualDisplay` backed by a `Surface` whose buffer is an OpenXR swapchain image or an `ImageReader`/`AHardwareBuffer` imported into it; start an activity on that display; show it on an `XrCompositionLayerQuad`. *The Java test app (`spikes/quad2d/`) measured the pixel path (195 frames in 8.4 s from a real Settings UI) and the engine's R4 step 2 puts the frames on a second quad layer in the headset.*
- [x] **Step 2:** Measure on the Frame: does it render, frame rate, latency of touch/pointer events mapped back to the virtual display (`input -d <displayId>` or injected `MotionEvent`s), and whether Waydroid permits a second display. *Measured: pixels arrive, `input -d <id>` taps change the frames, Waydroid permits extra displays; starting another app's activity needs a trusted display, so the host script launches apps (R4 steps 3 and 4).*
- [x] **Step 3:** Decide: build 2D windows in VR mode by this route, or fall back to the flat gamescope panel being shown beside the shell (if S3 says they coexist). *Decided: virtual display per window, pixels to an OpenXR quad, pointer mapped back with injected input; built in the engine plan's R4.*

### Task S5: Passthrough from an OpenXR app (done 2026-11-15: blend mode does not give passthrough)

- [x] **Step 1:** Using the frame-control notes (`/dev/video99`, `vrcmd --handlewakeup`, SteamVR room view), find what SteamVR exposes to an OpenXR app: blend modes the runtime advertises (`xrEnumerateEnvironmentBlendModes`), any passthrough extension, or only the compositor's room view. *Answered: OPAQUE and ALPHA_BLEND only, no passthrough extension; SteamVR's own room view is what an app can have.*
- [x] **Step 2:** Decide the shape of the later extension to `xr-layer/`: advertise `XR_FB_passthrough`, switch blend mode, or draw the camera feed ourselves. Record what each costs. *Decided after two measurements (the second with the headset worn): blend mode does not show the cameras, so V4 asks SteamVR for its room view as a background choice.*

---

## Phase 1: Steam mode (shippable without any VR work)

### Task 1: App catalog (done 2026-11-14)

**Files:**
- Modify: `bin/wgapps` (`catalog_build`, `catalog_refresh_labels`, `cmd_apps`, `usage`, `main`), `settings-app/` (`Labels.java`, `LabelsReceiver.java`, manifest), `tools/build-settings-app.sh`
- Create: `tests/test_catalog.py`, `tests/fixtures/apps-query-launcher.txt`, `tests/fixtures/apps-query-xr.txt`, `settings-app/test/LabelsTest.java`

**Interfaces:**
- Produces: `wgapps apps list` prints one app per line, tab separated: `package<TAB>label<TAB>activity<TAB>kind`, sorted by label (case folded) then package. `kind` is `xr` when the launcher component itself is in the `org.khronos.openxr.intent.category.IMMERSIVE_HMD` list (not just its package: Chrome lists a WebXR host activity there), else `2d`. `catalog_build <launcher-output> <xr-output>` (bash function, tested directly) builds the lines from Android's `cmd package query-activities --brief` output; the first launcher activity of a package wins.
- Labels: Android's command line gives label resource ids, never text (probed on the Frame). `$SHARE/app-labels.conf` (`package<TAB>label`) is written by the Settings app's `LabelsReceiver` at boot and when `wgapps apps list` sends it an explicit broadcast (`am broadcast -n dev.wgapps.settings/.LabelsReceiver`); the host waits up to 5 s for the new file and keeps the old one if none comes. Without the APK, or without a label, the label is the capitalised last part of the package name.
- Hidden: `$BASE/apps-hidden` (one package per line, `#` comments) plus a built-in list (`com.android.launcher3`, `com.android.documentsui`, `com.google.android.googlequicksearchbox`, `dev.wgapps.settings`). Settings stays visible.

- [x] **Step 1: Probe** on the Frame. Result: `cmd package query-activities --brief -a android.intent.action.MAIN -c <category>` lists components; no command gives label text. Real output saved as the two fixtures.
- [x] **Step 2: Tests** (`tests/test_catalog.py`, 17 tests; `settings-app/test/LabelsTest.java`), including the end-to-end `apps list` against a fake `podman`.
- [x] **Step 3: Run, expect failures.** Seen for the host tests; the Java test was written with its code, so it was checked by mutation instead (cut length, first-wins, control characters each made it fail).
- [x] **Step 4: Implement** the functions, the receiver, the manifest entry (`RECEIVE_BOOT_COMPLETED`, non-exported receiver) and the build step.
- [x] **Step 5: Full suite (133 tests) and linters; on the Frame:** `wgapps apps list` shows real names and kinds (Wolvic (Dev), Hello XR (Vulkan) and (OpenGL ES) are `xr`, Chrome is `2d`). The launcher and APK on the Frame match the repo. Note for deploys: Steam ignores a launch request for an app that is already running, so replacing the APK needs the Android entry quit (`SteamClient.Apps.TerminateApp`) and launched again.

### Task 2: Shortcut sync (done 2026-11-14)

**Files:**
- Modify: `bin/steam-shortcuts.py`, `bin/wgapps` (`cmd_apps sync`), `tests/test_shortcuts.py`
- Consumes: Task 1's `apps list`, Task S1's chosen mechanism.

**Interfaces:**
- Produces: `steam-shortcuts.py sync <catalog-file>` where each line is `package<TAB>label`; adds missing entries, removes ours whose package is gone, never touches others. Our entries are the ones whose Exe is the `wgapps` path and whose launch options start with `steam ` (no tags: Steam's `AddShortcut` takes none). With Steam running it uses the live mode (Steam's debug port, per `docs/superpowers/spikes/S1-live-shortcuts.md`: `AddShortcut` then `SetShortcutName` and `SetShortcutLaunchOptions`, app id read back from the return value); with Steam stopped it writes `shortcuts.vdf` as today. `wgapps apps sync` calls it. The base "Android" entry (no package) is always kept.

- [x] **Step 1: Tests** in `tests/test_shortcuts.py`: `test_sync_adds_missing_and_keeps_existing_appids_stable`; `test_sync_removes_our_entries_of_uninstalled_apps`; `test_sync_never_touches_entries_that_are_not_wgapps_launches`; `test_live_mode_issues_add_then_name_then_launch_options_and_uses_the_returned_id` (fake debug-port server); `test_falls_back_to_file_mode_when_the_debug_port_is_absent`; `test_sync_is_idempotent`; `test_file_mode_still_refuses_while_steam_runs`.
- [x] **Step 2: Run, expect failures. Step 3: Implement** `sync` in `steam-shortcuts.py` and `cmd_apps sync` in `bin/wgapps`.
- [x] **Step 4: Full suite and linters. On the Frame:** install a test APK, `wgapps apps sync`, the entry appears in Steam with the app's name; uninstall it, sync, the entry is gone; the three original shortcuts are untouched.

### Task 3: Attach-launch and exit watcher (done 2026-11-14)

**Files:**
- Modify: `bin/wgapps` (`cmd_steam`, `start_helpers`/`stop_helpers`)
- Create: `bin/wgapps-appwatch`, `tests/test_appwatch.py`
- Consumes: Task S2's decision: the entry that starts the container owns the panel; later entries attach and never restart or stop it; a missed panel for an attached entry and quitting the owner while others run are checked in Step 5.

**Interfaces:**
- Changes: `cmd_steam <pkg>` no longer restarts a running container. If the container is running it runs the app's launcher activity (`am start -n`) and waits until the app's process exits (via `wgapps-appwatch <pkg>`), then returns, so Steam's "running" state follows the app. If the container is not running it starts it as today (under this reaper) and then does the same. `trap` on TERM/INT/HUP force-stops only that package (`am force-stop <pkg>`) and, when it was the entry that started the container and no other app is running, stops the container as before.
- Produces: `wgapps-appwatch <package>`: polls `pidof`/`dumpsys` once a second and exits 0 when no process of the package remains, 1 if the container stops. Poll function separated from the loop for testing, like `bin/wgapps-profiles`.

- [x] **Step 1: Tests** in `tests/test_appwatch.py`: `test_exits_when_package_has_no_process`; `test_exits_nonzero_when_container_stops`; `test_one_missed_poll_does_not_end_it` (debounce, two consecutive misses); `test_package_name_is_validated_like_app_valid_package`. In `tests/test_apps.py` or a new `tests/test_steam_launch.py`: `test_second_launch_does_not_stop_a_running_container`; `test_quit_force_stops_only_that_package`; `test_first_launch_starts_the_container_under_the_reaper`.
- [x] **Step 2: Run, expect failures. Step 3: Implement. Step 4: Full suite and linters.**
- [x] **Step 5: On the Frame (verified):** launch two entries in turn: both apps run, no restart (check container uptime), quitting one from Steam leaves the other; quitting the app inside Android ends its Steam entry within a few seconds.

### Task 4: Window mode and per-app launch kind (done 2026-11-14)

**Files:**
- Modify: `bin/wgapps` (`write_props`, `cmd_start`, `cmd_apps`, `usage`), `settings-app/` (a row on the profile screen), `tests/test_apps.py`, `README.md`

**Interfaces:**
- Produces: `wgapps windows floating|single` stores `$BASE/windows`; `write_props` prints `persist.waydroid.multi_windows=true` for `floating` (nothing for `single`); `wgapps apps set <package> kind xr|2d|auto` is a new key in `apps.conf` (validators reused); `cmd_steam` passes it so an `xr` app is launched with the XR plumbing and a `2d` app shows the flat panel.

- [x] **Step 1: Tests:** `test_windows_floating_writes_multi_windows_prop_and_single_removes_it`; `test_windows_rejects_other_values`; `test_kind_key_is_validated_and_listed_in_app_list`; `test_windows_setting_survives_update`.
- [x] **Step 2: Run, expect failures. Step 3: Implement. Step 4: Full suite and linters.**
- [x] **Step 5: On the Frame (2026-11-16):** `wgapps windows floating`, restart: `persist.waydroid.multi_windows=true`, Settings and Chrome both `mode=freeform` as two overlapping windows with title bars in the one panel (screenshot); `single` restored and the test apps stopped.
- [x] **Step 6: README:** a "Steam mode" section: catalog, sync, launch, windows, and the limits (one panel, one Steam app id owns it).

---

**Done notes (2026-11-14; the Settings-screen row for the launch type was built 2026-11-16: a Launch type section on the per-app screen writes `app-kinds.conf`, `wgapps-profiles` takes it over with `wgapps apps kind-import`, checked on the Frame):** Task 2: `steam-shortcuts.py sync` (live and file modes, 17 tests, fake debug port); `wgapps apps sync`. Checked on the Frame with a test package: added live, second sync a no-op, removed again, the three original shortcuts untouched. A full `apps sync` was not run on the Frame (it would add about 20 entries to the library); run it when wanted. Task 3: `cmd_steam` attaches when Android runs; the owner still stops Android on quit; `wgapps-appwatch` ends an attached entry when its app has no process; verified on the Frame (same container start time before and after, quitting inside Android ended the entry in under 6 s, `TerminateApp` with the full game id force-stopped only Plex). Task 4: the CLI was checked on the Frame (windows get/set/reject, kind override and reset); the restart with `floating` was not repeated because the same property was verified in spike work on 2026-11-14 (step 5 stays open). Task 4 deviations: the kind is kept in `$BASE/apps-kind` (not `apps.conf`, which the Settings screen reads and rewrites), only `apps list` and the later shell use it (`cmd_steam` does not need it), and the Settings-screen row was not built.

## Phase 2: VR mode (Task M, V1 and V2 done; V3 and the status panel of V4 are the next project)

Status 2026-11-16: the spikes are answered (S3 to S5 above) and the shell was built in Rust on the Starforge engine instead of a `vr-shell/` APK (`2026-11-15-vr-shell-on-starforge.md`). What is left of this phase is the next project: `2026-11-16-vr-shell-next-project.md`.


### Task M: Mode switch (`wgapps mode steam|vr`) (done 2026-11-15)

Done: `cmd_mode` (get/set; `vr` refused without `lib/WgappsShell.apk`), `mode home [on|off]` in `$BASE/mode.conf`, `mount_shell_app` (priv-app, only when the effective mode is `vr`), `mode_record_start ok|fail` (three failures in a row set the saved mode back to `steam`). Not built: launching the shell at start and the Settings-screen row; both need the V1 app.

- [x] **Steps:** tests (`tests/test_mode.py`: default is steam; `vr` without `WgappsShell.apk` is refused with a clear message; switching writes `$BASE/mode` and takes effect at next start; the shell failing to start 3 times falls back to `steam` and says so); `cmd_mode`; `cmd_start` mounts the shell APK (priv-app, like `mount_settings_app`) and launches it only in `vr` mode; Steam mode behaviour unchanged. Settings screen row to pick the mode.

  **Status (2026-11-16):** Done: tests, `cmd_mode`, the shell mount and the three-failure fallback; the Settings screen's mode row (Steam Frame mode) was built 2026-11-16 and imports through `wgapps mode import`.

### Task V1: Shell skeleton (library and launch)

- [x] **Steps:** `vr-shell/` APK with an OpenXR scene: app grid from the catalog (`wgapps apps list` output pushed through the same shared-folder channel the Settings screen uses), controller ray and trigger select, launch via `am start`, return after the app closes (Task 3's watcher), a flat environment. Stack decided by S3/S4 (native OpenXR or Godot). Built by `tools/build-shell.sh`, optional like the Settings APK.

  **Status (2026-11-16):** Built as the Rust shell in the Starforge engine (`runtime-rust/xr-host`, engine plan R0 to R3) instead of a `vr-shell/` APK; `wgapps mode vr` runs it. See `2026-11-15-vr-shell-on-starforge.md`.

### Task V2: 2D app windows in the shell

- [x] **Steps:** by S4's decision: virtual displays as quad layers (move, resize, close, pointer), or the flat panel shown beside the shell. Per-window input mapping tests on the Frame.

  **Status (2026-11-16):** Built in the engine plan's R4: a virtual display and quad per window, pointer input, move and resize with the grip and thumbstick, the dock lists and closes windows.

### Task V3: Optional 3D home

- [ ] **Steps:** `home=on|off` in `$BASE/mode.conf`; environment layer behind the library and windows (starter room, saved layouts in a documented `.home` file format, autosave and export first); launcher panels placeable in the room; app objects (QuestHome's cartridge idea) as a later option. Assets CC0 only, per-item cost budget. With `home=off` the shell shows the plain environment.

  **Status (2026-11-16):** Not in this release: the plain 3D environment exists (engine plan V4), the optional 3D home with saved layouts and objects on the engine's renderer is the next project.

### Task V4: Passthrough and system controls

- [ ] **Steps:** extend `xr-layer/` per S5's decision so the shell can request passthrough; background layer choices (solid, home, passthrough); a status panel with the host's battery and volume and a few toggles via existing helpers (`wgapps-battery`); Wi-Fi, updates and room setup stay with SteamOS and SteamVR.

  **Status (2026-11-16):** Partly built: environment choices (room, solid colour, plain 3D home) exist; passthrough is SteamVR's room view (S5), so there is nothing to extend in `xr-layer/`. The host status panel and toggles are part of the next project.

---

> **Plan closed 2026-11-17 (release v0.1.5).** Done: Steam mode (catalog, live shortcut sync, attach-launch, windows),
> the mode switch, the Rust VR shell integration, the Settings screens (device profile, launch type, mode),
> hardware video decode, full-resolution OpenXR, the EGL layer against the Wolvic fullscreen-exit freeze
> (0 freezes in 146 exits, against 3 in 96 without it), and folder sharing with the Files app (`wgapps share`,
> optional idmapped mounts). CI runs in its own images and is green. Not in this release: the 3D home and the
> Rust launcher's remaining work (`2026-11-16-vr-shell-next-project.md`). Still open outside the plan:
> issues 1 and 2 wait for their reporters; the idmapped mounts are experimental until Android has been
> restarted with the mount in place on a Frame.

## Self-Review

- **Spec coverage:** Steam entries per app (Tasks 1, 2), tight Steam mode and attach-launch (Task 3), desktop management inside one panel (Task 4), VR-native launcher (V1, V2), optional 3D home (V3), passthrough (S5, V4), optional shell and a mode switch (M). The decision "one container" is in Global Constraints.
- **Placeholders:** Phase 2 tasks are deliberately outline-only and say so; Phase 1 tasks carry interfaces and tests.
- **Consistency:** `apps list` columns are used in Tasks 2 and V1 as defined in Task 1; `kind` is defined in Tasks 1 and 4; `wgapps-appwatch` is defined in Task 3 and consumed by V1.
- **Proportion:** Phase 0 and 1 are the executable part; the rest waits for spike findings.
