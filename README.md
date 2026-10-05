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

## Update, roll back, remove

```sh
W=~/.local/share/waydroid-gapps/bin/wgapps
$W update            # newest release; Android data is not touched
$W update v0.1.0     # a specific release
$W rollback          # undo the last update
$W uninstall --yes   # removes everything, including Android data
```

## Known limits

- Video decodes in software (fine for 1080p H.264/HEVC). Hardware decoding
  needs a V4L2 Codec2 HAL and is planned.
- Netflix and other Widevine L1 apps do not work (uncertified device).
- If Valve's Lepton is installed, its seccomp profile is used; otherwise
  podman's default profile.
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
- Tests: `cd tests && python3 -m unittest -v`. Lint: shellcheck, shfmt,
  ruff. CI runs on GitLab (`.gitlab-ci.yml`).
- `tools/deploy.sh` copies a checkout to a Frame over SSH in the release
  layout.
- Releases: development happens in a separate repository. A release tag
  there runs CI, which publishes `ghcr.io/tpmullan/steam-frame-android:vX.Y.Z`
  and `:latest` and pushes one snapshot commit per release here
  (`tools/release.sh`).
