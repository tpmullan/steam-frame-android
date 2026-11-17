# Fresh installs never finish booting: Lepton's seccomp profile fakes setuid

Status: **fixed** (`wgapps` always uses its own seccomp profile). Reported as GitHub issue 2
("boots endlessly"); reproduced on a Steam Frame with fresh GAPPS and VANILLA installs; verified
fixed on both (see "Verification").

## Symptom

A fresh `wgapps install` (Google apps or not) starts the container and Android never boots:

- `wgapps status`: `zygote=restarting`, `boot_completed` empty, `bootanim` running.
- No logcat (`logcat: Failed to wait for logd.ready to become true. logd not running?`).
- Android's init log (`$BASE/run/kmsg.log`), once per restart:
  `init: cannot execv('/system/bin/logd'). See the 'Debugging init' section ... Permission denied`.
- `wgapps` from the Steam entry or from a terminal behaves the same.

An older install (copied Lepton's profile before 2026-10-09) kept working, which is why the
maintainer's own Frame did not show it and a "fresh install" test was missing.

## Root cause

`wgapps install` copied Valve's Lepton seccomp profile (`Lepton/liblepton/lepton.seccomp.json`)
and used it for the Android container. Lepton changed that profile on **2026-10-09**: its
"answer with success without doing it" list (`SCMP_ACT_ERRNO` with `errnoRet 0`) gained
`setuid`, `setgid`, `setgroups`, `chown`, `fchown`, `fchownat`, `lchown`. Lepton's own Android
runs without separate service users, so that is harmless there. In our container (Waydroid's
rootfs, real service users through the id map) it is fatal:

1. init forks a child for `logd` and calls `setuid(1036)` (user `logd`). The call "succeeds" but
   does nothing: the child is still root, and init drops the capabilities it kept for itself.
2. `/system/bin/logd` is mode `0550`, owner and group `logd`. Root without
   `CAP_DAC_OVERRIDE` is neither, so `execv` fails with `EACCES`.
3. logd never runs; the other services that start as their own user fail the same way; zygote and
   SurfaceFlinger restart forever.

How it was found: the same GAPPS image booted in one base directory and not in another. Swapping
the images between bases (the VANILLA `system.img` booted in the "good" base, 152 packages) showed
the image was fine; the only file that differed between the bases was `lepton.seccomp.json`
(862 bytes from 2026-10-04 against 992 bytes from 2026-10-09). The three added lines of the
newer one were the identity calls.

## Fix

`bin/wgapps`: `cmd_start` always passes `write_seccomp` (our own allow-by-default profile; it
denies kernel modules, kexec, clock changes and `open_by_handle_at`, and fakes only `setpriority`,
`nice` and similar calls Android needs at boot). `install` no longer copies Lepton's profile and
deletes a copy left by an older install; `start` also deletes it. `wgapps report` says which
profile is used and whether Lepton is installed.

## Tests (reproductions)

| What | Test |
|---|---|
| The shape of the Lepton profile that broke installs | `tests/test_seccomp.py` `test_lepton_2026_10_09_fakes_the_identity_calls` (fixture `tests/fixtures/seccomp-lepton-2026-10-09.json`) |
| Why a faked setuid means `Permission denied` on a 0550 binary | `test_the_mechanism_a_faked_setuid_leaves_init_unable_to_exec_logd` |
| Our profile never fakes setuid/setgid/setgroups/chown, and still fakes `setpriority`/`nice` | `test_our_profile_never_fakes_the_identity_calls`, `test_our_profile_still_fakes_what_android_needs_at_boot` |
| `start` never uses Lepton's profile; install removes an old copy | `StartUsesOurProfileTests`, `tests/test_install_flavors.py` `InstallTests` |
| Fresh installs of **both** flavors: GAPPS (default) and VANILLA download the right system image, record the right marker, switching flavor re-downloads, a corrupt image is refused | `tests/test_install_flavors.py` `FetchImagesTests` (real `fetch-images.sh`, stub OTA, local zips) |
| `wgapps install` for both flavors: flavor remembered, GSF step only with Google apps, Lepton's profile never copied even when installed | `InstallTests` |

A unit test cannot boot Android; the boot is checked on a Frame:

## Verification

`tools`: boot a throwaway base (`WGAPPS_BASE`, `WGAPPS_NAME`, `WGAPPS_ADB_PORT` make a second
Android run beside the first) against a private headless gamescope (`gamescope --backend headless`)
-- Android's composer needs a Wayland display, so `start --headless` can never boot. With today's
Lepton profile installed on the Frame:

| Fresh base | boot | packages | Google apps | logd errors |
|---|---|---|---|---|
| VANILLA | `boot_completed=1` in about 15 s | 152 | 0 | 0 |
| GAPPS | `boot_completed=1` in about 15 s | 176 | 10 | 0 |

Before the fix the same fresh bases did not boot in 240 s (zygote restarting, 56-68 logd errors).

## Related

An earlier, separate bug gave the same "boots endlessly": with *no* Lepton installed, podman's
default seccomp profile refused `setpriority`, so init could not start zygote. Our own profile
fixed that one too (`write_seccomp` answers `setpriority` and `nice` with success). The init log
tells the two apart: `cannot set attribute for zygote: setpriority failed: Permission denied`
against `cannot execv('/system/bin/logd') ... Permission denied`.
