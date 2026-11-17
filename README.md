# Android with Google Play on the Steam Frame

Run everyday Android apps (Plex, YouTube, Reddit and others with Google Play)
on the Valve Steam Frame and launch them from the Steam library.

- Stock [Waydroid](https://waydro.id) LineageOS 20 GAPPS images, run in
  rootless podman, the way Valve's Lepton runs Android games.
- No root, no `steamos-readonly disable`. Everything lives under
  `~/.local/share/waydroid-gapps`, so SteamOS updates keep it.
- Hardware GPU (Mesa freedreno), audio, network, Google sign-in, offline
  downloads, and the Frame controllers as a TV remote in apps.

**This project ships no Android or Google software**, with one optional exception. The install step
downloads Waydroid's GAPPS images on your Frame directly from Waydroid's
servers (the same index `waydroid init` uses) and checks their SHA-256
against it. What this repo and its image contain is our launcher, controller
forwarder, Steam integration and small runtime overrides. The exception is the opt-in
[hardware video decode add-on](#hardware-video-decode-optional-unstable-in-testing): a 1 MB archive of
Apache-2.0 AOSP code built for this image, unpacked and used only if you ask for it
(`wgapps install --hwdec` or `wgapps hwdec install`; see [hwdec/NOTICE.md](hwdec/NOTICE.md)).

## What it does

| Feature | What you get | How |
|---|---|---|
| Android in the Steam library | Every Android app a Steam entry: live shortcut sync, launch, switch and quit from Steam | [Steam mode](#steam-mode-every-android-app-in-the-steam-library), `wgapps apps sync`, `wgapps windows` |
| Google apps or not | Waydroid's LineageOS 20 with Google apps (Play, sign-in), or without | `wgapps install [--vanilla]`, `wgapps gsf-id` |
| Per-app device profiles | Make an app see another device model (a Quest, a Pico) | [Per-app overrides](#per-app-overrides), `wgapps app` |
| Settings screens | In Android's Settings: Device profile per app, launch type per app, Steam Frame mode | [The Settings screen](#the-settings-screen) |
| VR mode (early) | A Rust VR shell: app library, apps as windows in the headset, controller pointer | [VR mode](#vr-mode-early), `wgapps mode`, `wgapps view` |
| Full-resolution OpenXR | Wolvic and other OpenXR apps render at the panel's resolution | [Render resolution](#render-resolution), `wgapps xr scale` |
| Your files in Android | The Frame's folders in Android's Files app, optionally idmapped so files stay yours | [Files app](#your-files-in-androids-files-app), `wgapps share` |
| Hardware video decode (optional, **unstable, in testing**) | 4K H.264 and VP9 on the SoC's decoder instead of in software | [Hardware video decode](#hardware-video-decode-optional-unstable-in-testing), `wgapps hwdec` |
| Wolvic freeze fix | A GLES layer avoids a Mesa deadlock that froze Wolvic after fullscreen video | [Freeze after leaving fullscreen video](#freeze-after-leaving-fullscreen-video), automatic |
| GPU choice | Mesa (default) or ANGLE for OpenGL ES | [GPU option: ANGLE](#gpu-option-angle), `wgapps gpu egl` |
| Updates | Update, roll back, uninstall; Android data is kept | [Update, roll back, remove](#update-roll-back-remove) |
| Diagnostics | One file to attach to a bug report; log runbook | [Troubleshooting](#troubleshooting-and-reporting), `wgapps report` |

`wgapps help` lists every command with its options. Public testers: [docs/testing.md](docs/testing.md) says what is solid, what is
still in testing and how to report.

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
adds an **Android** entry to the Steam library (while Steam runs it does so through
Steam's own client API, so you do not need to close Steam; if that is not possible it prints the
command to run later). `wgapps install --hwdec` also installs the optional hardware video
decoder (see [below](#hardware-video-decode-optional-unstable-in-testing)).

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
3. Add a Steam entry per app: `wgapps apps sync` adds one for every app you can open, or
   `~/.local/share/waydroid-gapps/bin/steam-shortcuts.py add Plex com.plexapp.android` for one
   (both work while Steam runs). In Steam, keep the default **Gamepad** controller layout for
   these entries.

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
each other's changes, and a choice applies the next time the app starts. The same
screen has a **Launch type in VR mode** section (Detected, VR app or Flat app), the
setting behind `wgapps apps kind`; it travels as `app-kinds.conf` and the helper
applies it with `wgapps apps kind-import`. A second entry, **System > Steam Frame
mode**, picks Steam mode or VR mode (`app-mode.conf`, `wgapps mode import`); VR mode
is refused, and the choice snaps back, when the shell is not installed.

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

## VR mode (early)

`wgapps mode` shows the mode; `wgapps mode env room|home|solid [#rrggbb]` picks what the Rust shell shows behind its panels (SteamVR's room view, a simple 3D space with a floor grid, or a solid colour); `wgapps mode vr` switches to the VR shell (needs
`lib/WgappsShell.apk`, built by `tools/build-shell.sh /tmp/out` like the Settings
APK, then copied to `~/.local/share/waydroid-gapps/lib/` with `WgappsShell.vr` when
the build had the NDK; restart Android). A Rust build on the Starforge engine
(`lib/StarforgeShell.apk`, package `rs.starforge.xrhost`) is used instead when it is
installed; it has the same library, tabs and dock and is built in the engine's repo
(`runtime-rust/xr-host`, `store-native-libs` on). The shell is an OpenXR panel in front of
you: a library of your Android apps with their icons (VR apps first), filter
tabs and a dock, styled after Android's launcher, Steam's library and Quest-style
panels ([design note](docs/superpowers/design/vr-shell-look.md)). Without the
NDK the build is a flat grid instead. With the Rust build the controllers point
at the panel with a beam, a trigger click launches an app (2D apps open as
movable window panels), the thumbstick scrolls, and a grip moves a window (the
thumbstick then resizes it). `wgapps view panel|vr` switches between the flat
panel and the VR shell. If the shell fails to start three times in a row, `wgapps` goes back to
`wgapps mode steam` and says so. `wgapps mode home on|off` stores the 3D-home
setting for later. `wgapps apps push` writes the app list the shell reads.

## Render resolution

SteamVR recommends rendering at 80% of the Frame's panel in each direction (1728 of 2160 pixels per eye), and OpenXR
apps such as Wolvic size their render targets from that alone, so everything is upscaled and looks soft. The OpenXR
layer in `xr-layer/` multiplies the recommendation by `wgapps xr scale` (default 1.25, which is the panel's own
2160x2160). `wgapps xr scale 1.0` turns it off, `wgapps xr scale default` restores 1.25, and a change applies
the next time Android starts. It costs about 56% more pixels; heavy scenes may need a lower value.

## Hardware video decode (optional, unstable, in testing)

**Status: unstable, in testing.** It is optional and off unless you ask for it, and it is not recommended on a
Frame you leave unattended. Android's own image has only Google's software video codecs, so YouTube stops at 1080p and 4K is
choppy or refused. The SoC's decoder (`qcom-iris`: H.264, HEVC and VP9 up to 8K) is a V4L2 device, and the
add-on is AOSP's Codec2 V4L2 service, built for this image with six patches
([tools/v4l2-codec2](tools/v4l2-codec2/README.md)), so Android can use it.

```sh
wgapps install --hwdec        # at install time, or later:
wgapps hwdec install          # unpacks the add-on from this release (checksum checked) and turns it on
wgapps hwdec status           # in the release? installed? on? decoder node usable?
wgapps hwdec off | on         # switch it without removing it
wgapps hwdec remove           # delete it
```

A change applies the next time Android starts. `update` keeps an installed add-on (and tells you in
`hwdec status` when the new release carries a newer one).

What was verified: Chrome and Wolvic decode a 4K VP9 clip and a YouTube 4K video on the decoder
(Android lists `c2.v4l2.vp9.decoder` and friends, the decoder's interrupt counter climbs), the add-on's
own check is `tools/decode-check.py`, and 150 scripted Wolvic runs decoded without a fault.

**Warning:** on one Frame the SoC's video codec reported a firmware error a minute or two after Android
started with the add-on on, and the kernel then crashed (`Unable to handle kernel paging request`),
rebooting the whole Frame. The cause is not known. Hence it is optional, unstable and still in testing: it is off unless you install it, and nothing else depends on it. If your Frame
reboots shortly after Android starts, run `wgapps hwdec off` and look in `journalctl -k` for `qcom-iris`.
`hwdec status` says whether the add-on will be used. HEVC is not offered by Android even so
(H.264 and VP9 are).

## Your files in Android's Files app

Android's own storage is private to the container, so nothing from the Frame was visible in the Files app.
`wgapps share` puts folders of the Frame inside it:

- `~/Android-share` is always shared, read-write, as the folder **Host** (created at the first start). Drop
  files there on the Frame or in Android's Files app and both sides can use them.
- `wgapps share add <path> [name] [--rw]` shares any other directory, your whole home directory included
  (`wgapps share add ~ Home`), read-only unless you say `--rw`. `wgapps share` lists them and
  `wgapps share remove <name>` stops sharing one (the folder itself is never touched). A change applies the
  next time Android starts.

What Android can see and do:

- Android's apps are other users than you. Sharing a folder adds Android's storage group to that one
  directory's ACL (list and read for read-only, plus write for read-write) and nothing else, and removing the
  share takes it away. Below the top level the folder's own permissions apply: your home directory is
  mode 0700, so it works only because of that ACL entry, and then Android sees what other users may
  read (a mode 0700 folder such as `~/.ssh` stays closed, a world-readable file does not). Think of
  sharing your home as handing every Android app, Google's included, every world-readable file in it.
- Files Android creates in a read-write folder belong to Android's own user, which you cannot read; the
  `wgapps-share` helper hands them to you (group read-write, so Android keeps its access) a few seconds later
  (about a minute for folders you added). Files you create there get the same access through the ACL.
- New files and folders show up on the other side at once. A file that already exists and is changed on the
  Frame can keep showing its old content in Android (Android's storage layer caches it; it did for
  over two minutes in testing), and an Android app that appends to it then overwrites your change. Replace
  files rather than editing them in place, and do not edit the same file on both sides at once.
- **Optional, needs root once: idmapped mounts.** `wgapps share idmap-setup` (it asks for your sudo password)
  installs a small boot unit (`/etc/wgapps/wgapps-idmap-mount` and `wgapps-idmap.service`, owned by root) that
  makes a second mount of each shared folder in which your user is shown as Android's storage user, and the
  reverse. Files then stay owned by you on disk, whoever made them, and the ACLs and the `wgapps-share` helper
  are no longer used for those folders. `wgapps share idmap-status` shows which method each folder uses,
  `idmap-remove` undoes it, and after `wgapps share add` run `idmap-setup` again to include the new folder.
  Checked on a real Linux 7.0 kernel with this helper and real rootless podman, and on a Frame with Android's own
  ID mapping: Android's storage user creates, edits and deletes files and folders in the folder, you read, edit
  and delete them, and everything stays owned by you on disk. Android can create files only in folders whose
  group is your own group (setup puts `~/Android-share` back to it); on a folder you added with another group
  it can read but not create. The boot unit itself ran on a Frame; the restart of Android with the mount in
  place was not tried, so treat it as experimental (needs Linux 5.12 or newer and ext4, xfs or btrfs under the
  folder).
- `/`, wgapps' own data and names Android's storage already uses (Download, DCIM, Music and so on) cannot
  be shared.

## Freeze after leaving fullscreen video

Mesa's Android EGL answers `eglQuerySurface(EGL_BUFFER_AGE_EXT)` by dequeuing the next back buffer with the display
lock held. If the thread that would free a buffer needs that lock, the app's frames stop for good: Wolvic froze a
few seconds after leaving a fullscreen 360 video. `lib/libwgapps_egl_layer.so` is a small GLES layer that Android's
libEGL loads (`debug.gles.layers`, from `/data/local/debug/gles`); it answers that one query with 0, which the
extension defines as "contents undefined", and passes every other call on. `WGAPPS_EGL_LAYER=0 wgapps start`
turns it off. Measured: 3 freezes in 96 exits without the layer, none in 146 with it (about a 1 in 100 chance if the
layer did nothing: very probably fixed, from two runs on one headset); details and the measurements are in the
[spike notes](docs/superpowers/spikes/S3-S4-S5-partial.md).

## GPU option: ANGLE

By default Android's OpenGL ES comes from Mesa (freedreno). Mesa has a locking
bug that can freeze an app (seen in Wolvic after leaving fullscreen 360 video).
`wgapps gpu egl angle` switches OpenGL ES to ANGLE on top of the Vulkan driver,
and the freeze does not happen. Restart Android after changing it.

```sh
W=~/.local/share/waydroid-gapps/bin/wgapps
$W gpu egl            # show the current choice (mesa by default)
$W gpu egl angle      # try ANGLE
$W gpu egl mesa       # back to the default
```

With ANGLE, the display's composer service still uses Mesa's EGL (it imports
Android's graphics buffers, which crashes ANGLE on this driver); `wgapps`
arranges that when it starts Android (details and tests:
[docs/bugs/2026-11-15-angle-composer-crash.md](docs/bugs/2026-11-15-angle-composer-crash.md)). Browsers, Chrome, Plex, Settings,
pointing at the panel and OpenXR apps that use Vulkan work. OpenXR apps that
use OpenGL ES with a depth buffer do not (OpenGL ES 3.1 only, and SteamVR
cannot share the depth image), which is why it is not the default.

## Troubleshooting and reporting

Report problems as an issue on [GitHub](https://github.com/tpmullan/steam-frame-android/issues). Run
`wgapps report` first and post its output in the issue (it holds no passwords or account data; skim it
before posting, since logcat can show app names). [docs/runbook-logs.md](docs/runbook-logs.md) says when to run
it and how to read Android's and the kernel's logs; [docs/testing.md](docs/testing.md) is the guide for
testers.

- **The Frame reboots or drops off the network a minute or two after Android starts:** look at
  `journalctl -b -1 -k` (the previous boot's kernel log). A `qcom-iris ... system error` followed by a
  kernel oops is the hardware decoder add-on: `wgapps hwdec off`.
- **The Frame goes to sleep and SSH drops** (deep suspend about a minute after idle): keep it awake for
  SSH while the display may still turn off, with a user service that blocks sleep:

  ```sh
  mkdir -p ~/.config/systemd/user && cat > ~/.config/systemd/user/wgapps-stay-awake.service <<'EOF'
  [Unit]
  Description=keep the Frame awake and reachable (blocks suspend; the display may still turn off)
  [Service]
  ExecStart=/usr/bin/systemd-inhibit --what=sleep --who=wgapps --why="keep the Frame reachable over ssh" --mode=block /usr/bin/sleep infinity
  Restart=always
  [Install]
  WantedBy=default.target
  EOF
  systemctl --user daemon-reload && systemctl --user enable --now wgapps-stay-awake.service
  ```

  Undo with `systemctl --user disable --now wgapps-stay-awake.service`.
- **Android loops at boot, or `wgapps start` from a terminal fails:** see the bug write-ups in
  [docs/bugs](docs/bugs) (seccomp profile, keystore owner, the wrong desktop session).
- **Android's shared folders show old content:** see the limits under
  [Your files in Android's Files app](#your-files-in-androids-files-app).

## Known limits

- Video decodes in software by default (fine for 1080p H.264/HEVC; YouTube stops at 1080p). The optional
  [hardware decode add-on](#hardware-video-decode-optional-unstable-in-testing) removes that limit for H.264
  and VP9, but is unstable and in testing: it has crashed a Frame's kernel once.
- Netflix and other Widevine L1 apps do not work (uncertified device).
- Lepton is not used. `wgapps` gives Android its own seccomp profile (everything
  allowed except kernel modules, kexec, clock changes and `open_by_handle_at`;
  `setpriority`/`nice` answered with success). Valve's Lepton profile is not
  compatible: since 2026-10-09 it fakes `setuid`/`setgid`, which stops Android
  from booting here ([docs/bugs/2026-11-15-lepton-seccomp-boot.md](docs/bugs/2026-11-15-lepton-seccomp-boot.md)).
- Some apps crash in the background on push notifications (Plex 2026.19);
  dismiss the dialog.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). This covers this project's own
files only. Waydroid's images and the Google apps in them are downloaded
from Waydroid under their own terms and are not part of this project. The optional
hardware decode add-on in `hwdec/` is AOSP code under the Apache License 2.0 (and `libchrome`
under BSD-3-Clause), with the notice and license text beside it ([hwdec/NOTICE.md](hwdec/NOTICE.md)).

## Development

- `bin/wgapps` is the entry point; `bin/wgapps-pad` forwards Steam's
  virtual Xbox pad; `bin/wgapps-ota` resolves Waydroid builds;
  `bin/wgapps-gen-overrides` derives the two vendor fixes from the
  installed image; `overrides/` holds our own init and network files.
- Tests: `python3 -m unittest discover -s tests -v` (needs git and **Python 3.12 or
  newer**: with an older `python3`, such as macOS's `/usr/bin/python3`, the tests
  stop with a message saying so). Lint: shellcheck,
  shfmt, ruff. CI runs on GitLab (`.gitlab-ci.yml`).
- `tools/deploy.sh` copies a checkout to a Frame over SSH in the release
  layout.
- Tools for testing on a Frame without a person in the headset (see
  [docs/debugging-the-frame.md](docs/debugging-the-frame.md)): `tools/gpu-trial.py` (regression checks and the
  unattended Wolvic fullscreen-exit harness, which dumps native stacks on a freeze), `tools/decode-check.py`
  (hardware decode end to end), `tools/frame-chaperone.py` (read and rotate SteamVR's zero poses),
  `tools/frame-pointer.py` and `tools/frame-aim-sweep.py` (simulated controllers and aim),
  `tools/xr-fixtures/` (a 360 test clip and page), `tools/package-hwdec.py` (pack a rebuilt decoder tree
  into `hwdec/`), `tools/build-android-libs.sh` (the OpenXR and GLES layers, the allocator lock and the
  property preload).
- CI runs in its own images; reproduce a failing job exactly by running that image (`python:3.12-alpine`,
  `koalaman/shellcheck-alpine:v0.10.0`, `mvdan/shfmt:v3.10.0-alpine`) on a throwaway container with the checkout
  copied in. Several portability bugs (no `/etc/localtime`, busybox `find`) only show there.
- Releases: development happens in a separate repository. Pushing a
  `vX.Y.Z` tag there builds and checks the image, publishes it as
  `ghcr.io/tpmullan/steam-frame-android:vX.Y.Z` (and `:latest` when it is
  the newest release), then pushes one snapshot commit and the tag here
  (`tools/sfa_release.py`).
