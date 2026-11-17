# S1: Add and remove Steam shortcuts while Steam runs

**Question:** `steam-shortcuts.py` refuses to write `shortcuts.vdf` while Steam runs. Can sync work with Steam running?

**Result: yes, through Steam's own client API over its web-UI debug port.** Verified on the Frame 2026-11-14.

- Steam is started with `-cef-enable-debugging`; the debug port listens on `127.0.0.1:8080` (`/json` lists the pages).
- The `SharedJSContext` page has `SteamClient.Apps.AddShortcut`, `RemoveShortcut`, `SetShortcutName`, `SetShortcutExe`, `SetShortcutStartDir`, `SetShortcutLaunchOptions`, `SetShortcutIcon`, `SetShortcutIsVR`, `SetShortcutSortAs`.
- Evaluating JavaScript there (`Runtime.evaluate`, `awaitPromise`) works with a stdlib-only websocket client; the Frame has no `websockets` module, so the client is about 90 lines (framing and the handshake).
- What was run: `AddShortcut("WGApps S1 test", "/usr/bin/true", "/tmp", "")` returned an app id (3647760851). The entry appeared at once but was named `true` (the executable's name), so `SetShortcutName(id, name)` and `SetShortcutLaunchOptions(id, opts)` are separate calls. A few seconds later `shortcuts.vdf` contained the name and the options. `RemoveShortcut(id)` removed it from the file.
- Restored: after the test `steam-shortcuts.py list` shows only Android, Moonlight and Plex; the test entry is gone from `shortcuts.vdf`; the helper script on the Frame was deleted.

**Decisions for Task 2**
- `steam-shortcuts.py` gets a live mode that talks to the debug port (`sync` uses it when Steam is running, and the existing file-writing path when it is not).
- Steam assigns the app id; read it back from `AddShortcut`'s return value, do not compute it. Our own crc32 `appid()` is only for the file-writing path.
- Identify our entries without tags: Exe is the `wgapps` path and the launch options start with `steam`. `AddShortcut` does not take a tag; a Steam collection or tag is optional and not needed.
- The debug port is local-only (`127.0.0.1`), enabled by Steam itself; if it is absent (Steam started without the flag), fall back to file mode and say so.
- Not tested: icons (`SetShortcutIcon`), whether the new entry's library artwork and "Play" button work on the first try, and launching it. Task 2's on-device step covers those.
