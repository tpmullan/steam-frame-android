# Runbook: gather logs for a bug report

Use this when Android will not start, boots forever, or an app freezes.
Run everything in a terminal on the Frame (Desktop Mode, or over SSH).

## 1. Collect

```sh
~/.local/share/waydroid-gapps/bin/wgapps report
```

It writes `~/wgapps-report-<date>.txt` and prints the path. The file holds the
wgapps version, SteamOS build, whether Steam and gamescope are running, the
container state and exit code, the last 200 lines of podman's log, Android's
init log (`run/kmsg.log`), the properties we set, and, if Android is up, the
last 1500 logcat lines and the tombstone list. It has no passwords, Google
account data or GSF ID. Open it and read it before you share it; logcat can
contain app names and URLs.

## 2. If Android boots forever

1. Leave it booting for two minutes, then run `wgapps status`. Note the
   `boot_completed`, `bootanim`, `sf` and `zygote` values.
2. Run `wgapps report` while it is still looping (the log is most useful
   then).
3. Stop it with `wgapps stop`, start it by hand with `wgapps start`, and run
   `wgapps wait-boot 120`. If that boots, the Steam entry is the problem; say so.

## 3. If an app freezes or crashes

1. Reproduce it, then run `wgapps report` straight away.
2. For a hang, also capture where it is stuck (replace the package):
   `wgapps sh 'debuggerd -b $(pidof com.example.app)' > ~/hang.txt`

## 4. What to put in the issue

- The report file, attached or pasted.
- What you did, what you expected, what happened.
- The Frame's SteamOS version and whether you started Android from the Steam
  entry or from a terminal.
