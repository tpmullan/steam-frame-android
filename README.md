# Android with Google Play on the Steam Frame

Run everyday Android apps (Plex, YouTube, Reddit and others with Google Play)
on the Valve Steam Frame and launch them from the Steam library.

- Stock [Waydroid](https://waydro.id) LineageOS 20 GAPPS images, run in
  rootless podman, the way Valve's Lepton runs Android games.
- No root, no `steamos-readonly disable`. Everything lives under
  `~/.local/share/waydroid-gapps`, so SteamOS updates keep it.
- Hardware GPU (Mesa freedreno), audio, network, Google sign-in, offline
  downloads, and the Frame controllers as a TV remote in apps.

**This project ships no Android or Google software.** The install step
downloads Waydroid's GAPPS images on your Frame directly from Waydroid's
servers (the same index `waydroid init` uses) and checks their SHA-256
against it. What this repo and its image contain is our launcher, controller
forwarder, Steam integration and small runtime overrides.

## Install

On the Frame, in a terminal (Desktop Mode, or SSH):

```sh
c=$(podman create ghcr.io/tpmullan/steam-frame-android:latest none) \
  && mkdir -p ~/.local/share/waydroid-gapps \
  && podman cp "$c:/wgapps/." ~/.local/share/waydroid-gapps/ && podman rm "$c" \
  && ~/.local/share/waydroid-gapps/bin/wgapps install
```

`install` checks prerequisites, downloads about 1.3 GB from Waydroid
(resumable: run it again if the connection drops), extracts the images and
adds an **Android** entry to the Steam library (close Steam first, or add it
later as printed).

For Android without Google apps, run `wgapps install --vanilla` instead (the
choice is remembered). To switch an existing install, run it again with the
other flag and expect a fresh Android: apps and data from the other image
are not carried over cleanly, so remove `~/.local/share/waydroid-gapps/data`
first if you want a clean start.

Then:

1. Launch **Android** from Steam. The first boot takes about a minute.
2. Google sign-in needs the device registered as uncertified:
   `~/.local/share/waydroid-gapps/bin/wgapps gsf-id` while Android runs,
   then enter the number at <https://www.google.com/android/uncertified>
   and wait a few minutes.
3. Add a Steam entry per app (with Steam closed):
   `~/.local/share/waydroid-gapps/bin/steam-shortcuts.py add Plex com.plexapp.android`.
   In Steam, keep the default **Gamepad** controller layout for these
   entries.

## Controls

The pointer works as a touchscreen. Controller buttons act as a TV remote:

| Button | Android |
|---|---|
| A | Select (show player controls) |
| B | Back |
| X | Play/pause |
| D-pad | Navigate, seek |
| LB / RB | Rewind / fast-forward |

## Per-app overrides

Some apps choose their controllers or features by the device model Android
reports, and a headset they have never heard of gets the bare minimum. Instead
of patching each app, tell Android to report something else to one app only:

```sh
W=~/.local/share/waydroid-gapps/bin/wgapps
$W app set com.igalia.wolvic.vanilla model "Quest 3"
$W app list
$W app unset com.igalia.wolvic.vanilla          # or: ... unset <package> model
```

Keys are `model`, `manufacturer`, `brand` and `device`; each sets every copy of
that property Android keeps (`ro.product.model`, `ro.product.vendor.model`, ...),
so Java's `Build.MODEL` and native code agree. Values are 1-91 letters, digits,
spaces and `. _ + ( ) / : -`; package names are at most 54 characters. The
settings live in `apps.conf` next to the scripts, survive updates, and apply at
Android's next start. While Android runs, a change reaches the app the next
time it starts (`wgapps sh am force-stop <package>`).

### The Settings screen

With `lib/WgappsSettings.apk` installed, Android's own Settings has **System >
Device profile per app**: a list of your apps and, per app, radio choices like a
permission's (Default, Meta Quest 3 / 3S / Pro / 2, Pico 4 / 4 Ultra, or a model
you type). It writes the same settings as `wgapps app set`, the two always show
each other's changes, and a choice applies the next time the app starts.

Build and install it (needs the Android SDK, JDK 11+; the APK is not in the
release, which forbids APKs):

```sh
tools/build-settings-app.sh /tmp/out
scp /tmp/out/WgappsSettings.apk steamos@frame:.local/share/waydroid-gapps/lib/
```

then restart Android. Android lists extra Settings screens only from system
apps, so `wgapps start` mounts the APK under `/system/priv-app`; nothing is
installed into Android's data. The screen and the host talk through
`device-profiles.conf` in the folder shared with Android, which `wgapps start`
makes world-writable (every user ID in the container is a sub-ID of yours), and
the `wgapps-profiles` helper applies a changed file with `wgapps app import`.

How it works and what it costs: Android's `wrap.<package>` property runs an
app's main process through a preload (`libwgapps_props.so`) that overwrites the
property in that process's own copy of Android's property area. Nothing else,
and no other app, sees it. An app started this way is not forked from Android's
zygote, so it starts a little slower and Android logs one harmless
`SIGSYS` crash report for a helper process each time it starts. Only the app's
main process is covered, not its `:service` processes. Properties stored next to
an overridden one stop updating in that process, which is fine for the
read-only `ro.product.*` ones this is meant for.

## Steam mode: every Android app in the Steam library

Android runs as one container and one panel in gamescope. Steam mode puts each Android app in the
Steam library, so you launch, switch and quit them from Steam like any game.

- `wgapps apps list` prints what you can open: package, name, launcher activity, and `kind` (`xr`
  for an OpenXR app such as Wolvic or hello_xr, `2d` otherwise). Names come from the Settings app,
  so keep `WgappsSettings.apk` installed; without it names fall back to the package's last part.
  Hide an app by adding its package to `~/.local/share/waydroid-gapps/apps-hidden`; override the
  detected kind with `wgapps apps kind <package> xr|2d|auto`.
- `wgapps apps sync` makes the library match: one shortcut per app, and the shortcuts of apps you
  uninstalled are removed. It never touches shortcuts that are not `wgapps steam <package>`
  launches, and keeps the base "Android" entry. With Steam running it adds and removes them live
  through Steam's own debug port (Steam must be started with `-cef-enable-debugging`, as on the
  Frame); with Steam closed it edits `shortcuts.vdf`. Give new entries the default Gamepad layout.
- The first entry you launch starts Android and owns the panel (overlay, Quit). Entries you launch
  after that attach to the running Android: they open their app, never restart Android, and end
  when you quit the app inside Android. Quitting an attached entry from Steam stops only that app;
  quitting the first entry stops Android, and every app with it.
- `wgapps windows floating` opens apps as movable windows inside that one panel; `single` (the
  default) makes each app fill it. It applies when Android next starts and survives updates.

Limits: Steam sees one window (one Steam app id owns the panel), so there are no separate panels per
app, and apps share one Android, with no isolation between them. For isolation, use Lepton.

## Update, roll back, remove

```sh
W=~/.local/share/waydroid-gapps/bin/wgapps
$W update            # newest release; Android data is not touched
$W update v0.1.0     # a specific release
$W rollback          # undo the last update
$W uninstall --yes   # removes everything, including Android data
```

## Reporting a problem

`wgapps report` writes a diagnostics file (no passwords or account data) to attach
to an issue; [docs/runbook-logs.md](docs/runbook-logs.md) says when to run it.

## Known limits

- Video decodes in software (fine for 1080p H.264/HEVC). Hardware decoding
  needs a V4L2 Codec2 HAL and is planned.
- Netflix and other Widevine L1 apps do not work (uncertified device).
- Lepton is optional. `wgapps install` uses Valve's seccomp profile for Android
  when Lepton is installed at that moment, and otherwise writes its own: it
  allows everything except kernel modules, kexec, `open_by_handle_at` and
  changing the clock, and answers `setpriority`/`nice` with success, which
  Android needs to boot (podman's default profile blocks it and Android never
  finishes booting). Android boots either way. To switch, install or remove
  Lepton and run `wgapps install` again; it picks the profile to use and says
  which. Valve's profile follows their testing; ours is the minimum that boots.
- Some apps crash in the background on push notifications (Plex 2026.19);
  dismiss the dialog.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). This covers this project's own
files only. Waydroid's images and the Google apps in them are downloaded
from Waydroid under their own terms and are not part of this project.

## Development

- `bin/wgapps` is the entry point; `bin/wgapps-pad` forwards Steam's
  virtual Xbox pad; `bin/wgapps-ota` resolves Waydroid builds;
  `bin/wgapps-gen-overrides` derives the two vendor fixes from the
  installed image; `overrides/` holds our own init and network files.
- Tests: `cd tests && python3 -m unittest -v` (needs git). Lint: shellcheck,
  shfmt, ruff. CI runs on GitLab (`.gitlab-ci.yml`).
- `tools/deploy.sh` copies a checkout to a Frame over SSH in the release
  layout.
- Releases: development happens in a separate repository. Pushing a
  `vX.Y.Z` tag there builds and checks the image, publishes it as
  `ghcr.io/tpmullan/steam-frame-android:vX.Y.Z` (and `:latest` when it is
  the newest release), then pushes one snapshot commit and the tag here
  (`tools/sfa_release.py`).
