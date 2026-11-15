# Per-app overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** `wgapps app set <package> model "Quest 3"` makes that one app (and no other) see a different device model, so apps that pick controllers or features by headset name work without patching each app.

**Architecture:** Android honours a per-package property `wrap.<package>` (this image is `userdebug`, `ro.debuggable=1`; verified on the Frame: it preloads a library into that app's main process only). The property preloads `libwgapps_props.so` and names the package. At load the library reads a per-package file and writes each value into the process's own copy of Android's property area (it replaces the mapped page with a private copy), so native code, Java's `Build.MODEL` and direct libc callers all see it. The host keeps the settings in `$BASE/apps.conf` (survives `update`), and `bin/wgapps` generates the per-package files, mounts them and sets the properties.

> **Design change found on the Frame (2026-11-10):** the first design intercepted `__system_property_get/find/read/read_callback`. It loaded but Wolvic still saw the real model: an app's own native libraries live in a linker namespace that a preload does not reach, and Wolvic reads `ro.product.vendor.model`, not `ro.product.model`. Hence the page patch, and each key setting every per-partition copy (`ro.product.{,system.,vendor.,odm.,system_ext.,vendor_dlkm.,product.}<key>`). A wrapped app is not forked from the zygote, so Android runs its zygote-only setup in the app and one helper process dies of `SIGSYS` per start (harmless; documented in the README).

**Tech Stack:** C11 (freestanding, built like `gbm-lock/` by `tools/build-android-libs.sh`), bash (`bin/wgapps`), Python `unittest` (`tests/`).

**Spec:** the user's request in this session: "We should probably have an addition to the settings in our Android that give per app override" and "randomly patch every app in the world doesn't make sense to do forever". Model-name override first; the design leaves room for more keys.

## Global Constraints

- Property values are at most 91 characters (`PROP_VALUE_MAX` 92 with NUL); a `wrap.` value is `LD_PRELOAD=/data/wgapps/props.so WGP=<package>` = 37 + package length, so a package name is at most 54 characters.
- Keys: `model`, `manufacturer`, `brand`, `device`. Each sets every per-partition copy, `ro.product.{,system.,vendor.,odm.,system_ext.,vendor_dlkm.,product.}<key>` (Wolvic reads `ro.product.vendor.model`, Java's `Build.MODEL` reads `ro.product.model`); the library skips a property this Android does not have.
- Values match `^[A-Za-z0-9 ._+()/:-]{1,91}$` (no quotes, `;`, `$`, backslash: the value is never shell-quoted by hand, and the allowed set cannot break the `wrap` command).
- Package names match `^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$`.
- Container paths: library `/data/wgapps/props.so`, per-package files `/data/wgapps/props.d/<package>` (one `name=value` per line). `/data` is the one place an app may load a preload from.
- A missing preload library is fatal to the app that names it: the `wrap` property is only ever set when the library is mounted.
- Settings live in `$BASE/apps.conf`, one `<package> <key>=<value>` per line; `update` and `rollback` do not touch it.
- No new tool dependencies: the library links only `libc.so libdl.so liblog.so` stand-ins (add what it needs from libc to the stand-in list).
- Shell must pass `shellcheck -x` and `shfmt -d`; Python `ruff@0.13.0` check and format.

## Review Focus

- An app with no override sees every property unchanged, and so does every other property of an overridden app (test in Task 1).
- Missing, empty or garbled per-package file, or `WGP` unset: pass-through, no crash (Task 1).
- A value that would break the `wrap` shell command (`'`, `;`, `$(…)`, newline) or a 55-character package is rejected by `app set`, and nothing is written (Task 2).
- Library file absent: no `wrap.` property and no mounts for it, the container still starts (Task 2).
- First property reads from several threads at once load the file once and agree (Task 1).
- `app unset` clears the live property and the file, so the app is back to the real model on its next start (Task 2, verified on the Frame in Task 3).

---

### Task 1: The preload library

**Files:**
- Create: `props-override/props_override.c`, `props-override/test_props_override.c`
- Modify: `tools/build-android-libs.sh`, `tools/build-image.sh:21`, `tools/sfa_release.py:54`

**Interfaces:**
- Produces: `libwgapps_props.so`, exporting nothing: a constructor reads `getenv("WGP")` (package) and `/data/wgapps/props.d/<package>` and patches the properties that exist (a fake property area in the host test).

- [x] **Step 1: Write `test_props_override.c`** (host test; `#define WGAPPS_PROPS_TEST` and `PROPS_DIR`, then `#include "props_override.c"`; a fake two-page property area whose `prop_info`s match Android's layout, `__system_property_find` defined by the test). Tests: the override is what a reader of the area sees (value, length bits, counter kept, not dirty); other properties untouched; a property across a page boundary patched whole; several overrides; the area stays read-only; no `WGP`; another package's file; names that are not package names (`../x`, `sub/x` that exists, `..`, `.hidden`, spaces, 80 characters); garbled lines; a property that does not exist is not created; a long property left alone; a 120-character value cut to 91; a later line wins; more lines than a table holds. Verified by mutation (length bits, second page, long flag, writable page, leading dot, slash, length limit each make it fail).
- [x] **Step 2: Run it, expect build failure** (`props_override.c` missing): `HOST_CC=cc cc -std=c11 -Wall -Wextra -Werror -pthread -o /tmp/t props-override/test_props_override.c && /tmp/t`.
- [x] **Step 3: Implement `props_override.c`.** `apply_overrides()` (constructor) reads the file into a static 4 KiB buffer and calls `set_property(name, name_length, value, value_length)` per `name=value` line: find the property with libc's `__system_property_find`, skip it if absent or long, copy its pages to a static buffer, `mmap` an anonymous private page over them with `MAP_FIXED`, copy back, write the value and the length bits of the serial, `mprotect` read-only. No `malloc`, no dynamic symbol lookup.
- [x] **Step 4: Run the host test, expect all pass.**
- [x] **Step 5: Wire the build.** `tools/build-android-libs.sh`: host test, `android_lib libwgapps_props.so … "libc.so liblog.so" ""` (no exports); libc stand-ins gain `open read close getenv strlen mmap mprotect getpagesize __system_property_find`. `libwgapps_props.so` added to the loop in `tools/build-image.sh` and the tuple in `tools/sfa_release.py`. Built with the NDK on the Mac and in `debian:bookworm-slim` (the CI recipe), both ok.
- [ ] **Step 6: Commit** (not done: only on request; the working tree already holds other uncommitted work).

### Task 2: `wgapps app` and the container plumbing

**Files:**
- Modify: `bin/wgapps` (new section after `mount_gbm_lock`; `usage`; `main`; `cmd_start`; `write_props`)
- Create: `tests/test_apps.py`

**Interfaces:**
- Consumes: Task 1's library at `$BASE/lib/libwgapps_props.so`.
- Produces (bash, sourced by tests like `tests/test_xr.py` does): `app_valid_package PKG`, `app_valid_key KEY`, `app_valid_value VALUE` (return 0/1); `cmd_app set|unset|list …`; `generate_app_props` (writes `$RUNDIR/props.d/<pkg>`, removing stale files but keeping the directory); `app_wrap_props` (prints `wrap.<pkg>=LD_PRELOAD=/data/wgapps/props.so WGP=<pkg>` lines, nothing when the library is absent); `mount_app_props` (binds the library and `$RUNDIR/props.d`, nothing when the library is absent).

- [x] **Step 1: Write `tests/test_apps.py`** (`unittest`, temp `WGAPPS_BASE`, run bash functions through a small helper in `tests/helpers.py` modelled on `wgapps_mounts`). Tests: `test_set_writes_apps_conf` (`cmd_app set com.igalia.wolvic.vanilla model "Quest 3"` → file contains `com.igalia.wolvic.vanilla model=Quest 3`); `test_set_replaces_same_key_keeps_others`; `test_unset_key_and_unset_package`; `test_list_prints_conf`; `test_rejects_bad_values_and_writes_nothing` (values `a'b`, `a;b`, `$(x)`, "a\nb", empty, 92 chars; key `foo`; package `bad pkg`, 55-char package); `test_generate_writes_props_files` (`com.x.y` file has `ro.product.model=Quest 3`; a stale file for a removed package is deleted; directory inode unchanged); `test_wrap_props_lines` (exact line, length ≤ 91); `test_no_wrap_props_or_mounts_without_the_library`; `test_mounts_library_and_props_dir` (destinations `/data/wgapps/props.so` ro, `/data/wgapps/props.d` ro).
- [x] **Step 2: Run `python3 -m unittest tests.test_apps` (from `tests/`: `python3 -m unittest discover -s tests -p 'test_apps.py'`), expect failures** (functions missing).
- [x] **Step 3: Implement the functions in `bin/wgapps`** with the Global Constraints' regexes (`[[ =~ ]]`). `cmd_app set` rewrites `apps.conf` through a temp file then `mv`; validation happens before any write. After a change it calls `generate_app_props` and, if the container is running, applies the property live: `asys` with `setprop wrap.<pkg> '<value>'` for set, `setprop wrap.<pkg> ''` when the package has no overrides left; it then prints "takes effect the next time the app starts (am force-stop <pkg>)".
- [x] **Step 4: Hook into start.** `cmd_start` calls `generate_app_props` before the mounts and `mount_app_props` next to `mount_gbm_lock`; `write_props` appends `app_wrap_props` output (inside the existing brace group, before `device.prop`). Add the `app` lines to `usage` and `app) cmd_app "$@" ;;` to `main`.
- [x] **Step 5: Run the full suite** `python3 -m unittest discover -s tests` (expect all OK, previously 74), then `shellcheck -x bin/wgapps tools/*.sh`, `uvx --from shfmt-py shfmt -d bin/wgapps tools/*.sh`, `uvx ruff@0.13.0 check . && uvx ruff@0.13.0 format --check .`.

### Task 3: Prove it on the Frame, document it

**Files:**
- Modify: `README.md` (a short "Per-app overrides" section), memory `xr-port-status.md`

- [x] **Step 1: Deploy** `bin/wgapps`, `lib/libwgapps_props.so` to `~/.local/share/waydroid-gapps/{bin,lib}` (previous `bin/wgapps` kept as `wgapps.prev`), restart the container with the recipe in memory, `wait-boot`.
- [x] **Step 2: Baseline.** `bin/wgapps app set com.igalia.wolvic.vanilla model "Quest 3"`; force-stop and start Wolvic; expect in logcat `wgapps-props: com.igalia.wolvic.vanilla: 1 override(s)` and Wolvic's "Device … is not supported" line gone / its device type changed; `bin/wgapps sh getprop ro.product.model` still prints the real model; hello_xr in the same container still sees the real model (check its log or `am start` + logcat tag).
- [x] **Step 3: Undo path.** `bin/wgapps app unset com.igalia.wolvic.vanilla`; force-stop/start Wolvic; the "not supported" line returns; `getprop wrap.com.igalia.wolvic.vanilla` empty.
- [x] **Step 4: Survive a restart.** Set again, `bin/wgapps stop`/`start`, expect the override applied at boot (via `waydroid.prop`) without running `app set`.
- [x] **Step 5: Re-run all three XR test apps** (hello_xr GLES, Vulkan, Wolvic) for frames presented and no fatal signals, so nothing regressed.
- [x] **Step 6: Write the README section and update the memory file.** Leave the Frame with Wolvic's override unset (our own Wolvic build no longer needs it).
