# keystore2 aborts at boot after a boot under Lepton's seccomp profile

Reported on issue 2 (2026-11-15, after the seccomp fix): "I can see the Android interface for a
second, then it crashes and boots up again, another loop." Reinstall had kept the existing data.

## Symptom

`logcat -b crash` is full of the same abort, every ~6 s, from `/system/bin/keystore2` (uid 1017):

```text
Abort message: 'Failed to open database.: Failed to attach database persistent.
    0: unable to open database: file:/data/misc/keystore/persistent.sqlite
    1: Error code 14: Unable to open the database file'
```

`os_unix.c: (13) open(/data/misc/keystore/persistent.sqlite)` is errno 13, EACCES. The composer's
"Binder threadpool cannot be shrunk after starting" aborts in the same log are a side effect of
services restarting.

## Cause

Lepton's profile of 2026-10-09 fakes `setuid`, `setgid`, `setgroups` and `chown`
(docs/bugs/2026-11-15-lepton-seccomp-boot.md). A boot under it runs keystore2 as root, which creates
`/data/misc/keystore/persistent.sqlite` as `root:root 0600`. wgapps' own profile fixed the boot, but
the data stays: keystore2 now runs as uid 1017 and cannot open the root-owned file. Android's init
re-owns directories it creates (`mkdir`), not the files inside.

## Reproduction (Steam Frame, throwaway second instance)

1. Fresh data, boot with Lepton's 2026-10-09 profile (`tests/fixtures/seccomp-lepton-2026-10-09.json`):
   `persistent.sqlite` appears as `0 0`, `zygote=restarting`.
2. Same data, boot with the fixed wgapps: `logcat -b crash` shows the abort above, twice within 6 s.

## Fix

`wgapps start` runs `repair_keystore_owner` inside `podman unshare` before the container starts: any
file under `data/misc/keystore` not owned by uid 1017 (AID_KEYSTORE) is handed to it. With the repair,
the same data boots: 0 aborts, `persistent.sqlite` is `1017 1017`, `system_server` up, 176 packages.

Tests: `tests/test_keystore_owner.py`.

## Not covered

Other files created as root during that era (resource-cache idmaps and similar) are rebuilt by
Android. If another path turns out to matter, add it next to `repair_keystore_owner`; a clean
`wgapps uninstall` and `install` is the fallback and does lose Android data.
