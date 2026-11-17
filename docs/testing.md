# Testing guide for public testers

Thank you for trying this. This page says what is solid, what is still in testing, what to try, and what to send us.
The [README](../README.md) has the full feature list and commands.

## What is solid

- Android with or without Google apps, started from Steam, with every app as a Steam entry (`wgapps apps sync`).
- Per-app device profiles, and the Settings screens (device profile, launch type, Steam Frame mode).
- Wolvic and other OpenXR apps at the panel's resolution (`wgapps xr scale`), and the fix for Wolvic freezing
  after leaving fullscreen video (measured: no freeze in 146 exits, against 3 in 96 without the fix).
- Sharing `~/Android-share` and other folders with Android's Files app (`wgapps share`), with the limits listed
  in the README (a file you change on the Frame can keep showing old content in Android for a while).
- Update, roll back and uninstall; your Android data is kept across updates.

## In testing (optional, off by default, please tell us how it goes)

| Feature | Turn it on | Turn it off | What to know |
|---|---|---|---|
| **Hardware video decode** (unstable) | `wgapps install --hwdec` or `wgapps hwdec install` | `wgapps hwdec off` | 4K H.264 and VP9 on the SoC's decoder. On one Frame it caused a kernel crash and a reboot. Do not leave a Frame running it unattended. |
| **Idmapped shared folders** (experimental) | `wgapps share idmap-setup` (asks for sudo once) | `wgapps share idmap-remove` | Files Android creates stay owned by you. Tested with Android's own ID mapping; not yet run across many boots. |
| **VR mode / VR shell** (early) | `wgapps mode vr` | `wgapps mode steam` | Needs the shell APK; see the README. |
| **ANGLE** (GPU option) | `wgapps gpu egl angle` | `wgapps gpu egl mesa` | See the README before using it. |

Restart Android after changing any of these.

## What would help most

1. A fresh install of the release (`wgapps install`, with and without `--vanilla`) and whether Android boots.
2. Hardware decode, if you are willing: `wgapps hwdec install`, restart Android, play a 4K video in Chrome or
   Wolvic, and tell us whether the Frame stayed up. `wgapps hwdec status` shows whether it is in use.
   If the Frame reboots, run `journalctl -b -1 -k | grep -i -E "qcom-iris|Unable to handle"` and send the output.
3. Folder sharing: drop a file into `~/Android-share` and open it from Android's Files app, and the other way round.
4. Anything that crashes, freezes or does not start.

## How to report

Report problems as an issue on GitHub: <https://github.com/tpmullan/steam-frame-android/issues>. Please do not
describe a problem without the logs. Run our log-gathering script and post its output:

```sh
~/.local/share/waydroid-gapps/bin/wgapps report            # writes a file and prints where
```

`wgapps report` collects the release and SteamOS versions, the container's state and its log, Android's init log,
the properties wgapps sets, which seccomp profile is used, `wgapps hwdec status`, and Android's logcat when Android
is up. It holds no passwords or Google account data, but logcat can show app names, so skim it before posting. Paste
the output into the issue, or attach the file.

Then add, in the issue:

- what you did, what you expected, and what happened,
- if the Frame rebooted or dropped off the network: the previous boot's kernel log,
  `journalctl -b -1 -k | tail -200` (run it after the reboot; it is not part of `wgapps report`),
- which optional features you had turned on (`wgapps hwdec status`, `wgapps share idmap-status`).

[docs/runbook-logs.md](runbook-logs.md) says when each log helps.

## Keeping the Frame reachable while you test over SSH

The Frame suspends about a minute after going idle, which drops SSH. The README's *Troubleshooting* section has a
small user service that blocks sleep (the display may still turn off).
