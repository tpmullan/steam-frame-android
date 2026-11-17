# `wgapps` fails from a terminal in another desktop session

Status: **fixed** (`wgapps` sets `XDG_RUNTIME_DIR` and the session bus itself). Seen in GitHub
issue 2: the reporter's terminal had `XDG_RUNTIME_DIR=/run/user/1000/nested_plasma`.

## Symptom

From such a terminal, with Android running (started from the Steam entry):

- `wgapps logcat` / `podman exec`: `container ... does not exist: open
  /run/user/1000/nested_plasma/crun/<id>/status`;
- `wgapps status` printed `stopped` for a running Android;
- `wgapps stop` then `start`: `StopSignal SIGTERM failed ...` and
  `crun: sd-bus call: Process org.freedesktop.systemd1 exited with status 1: Input/output error`.

## Cause

Rootless podman keeps container state under `$XDG_RUNTIME_DIR` and talks to the user's systemd
over `$DBUS_SESSION_BUS_ADDRESS`. The container was created by the Steam session
(`/run/user/<uid>`); a shell in a nested session has other values, so podman looks in the wrong
place. Reproduced read-only on a Frame: `XDG_RUNTIME_DIR=/tmp/other-session wgapps status` printed
`Failed to obtain podman configuration: lstat ...` and then `stopped`.

## Fix

`bin/wgapps` sets `XDG_RUNTIME_DIR=/run/user/<uid>` at the top and, if `bus` exists there,
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus`, for everything it runs. Verified: from
`XDG_RUNTIME_DIR=/tmp/other-session` and `/run/user/1000/nested_plasma`, `status` says `running`
and `logcat` works.

Tests: `tests/test_session.py` (a foreign, empty or unset runtime dir is replaced; the bus follows).
Not covered: starting Android from a nested session, which also needs that session's Wayland
socket and cgroup scope; start it from the Steam entry.
