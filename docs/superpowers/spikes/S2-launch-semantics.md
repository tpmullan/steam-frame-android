# S2: Launch semantics with several Steam entries

**Question:** What happens when a second entry is launched while Android runs, and can it attach instead of restarting?

Verified on the Frame 2026-11-14 with a temporary second entry (created and removed through the live API from S1).

**Today's behaviour (`cmd_steam` restarts a running container):** launching the second entry restarted the container (start time 03:55:05 to 04:15:32). The first entry's reaper ended, the second app id (4004056758) took the panel and gamescope focus, and its app opened. Each launch replaces the previous one.

**Candidate behaviour (attach, no restart), tested with a stand-in script:** the script ran `am start`, trapped TERM/INT/HUP to `am force-stop` that one package, and polled `pidof` for the package.
- Container start time unchanged (04:17:36). Both reapers alive (first app id 3239304162, second 4004056758).
- `GAMESCOPE_FOCUSED_APP` stayed with the first entry; the second entry's app was in front inside Android's window.
- Quit the second entry from Steam (`SteamClient.Apps.TerminateApp("<gameid>", false)`): the script trapped the signal, force-stopped only that app, its reaper ended, Android went back to the launcher, the container and first entry were untouched.
- Closed the app inside Android (`am force-stop`): the script's loop noticed within the poll interval and exited ("app exited" in its log) so Steam's "running" state follows the app. (My reaper counts in that step included my own shell's command line, so the evidence is the script's log, not the count.)

**Decisions for Task 3**
- The first entry that starts the container owns the panel (gamescope maps the Wayland client to its reaper). Later entries attach; they run `am start`, then watch the package, and never restart or stop the container themselves.
- Quitting an attached entry force-stops only its package. Quitting the owner entry stops the container (as today), which ends the attached apps; this must be documented.
- Polling `pidof <package>` through `podman exec` once a second is enough (a second of delay at exit).
- Not tested: whether the attached entry gets a blank SteamVR panel of its own (an overlay line for the second app id appeared, but I did not screenshot it), and what happens if the owner entry is quit while others run. Task 3's on-device step must check both.

**Cleanup:** the temporary entry and all files under `/tmp` were removed; `steam-shortcuts.py list` shows Android, Moonlight and Plex. Android is running, started under the Android entry.

**Mistake worth remembering:** `pkill -f "<pattern>"` over SSH matched its own shell's command line and killed the session; use a pid from `pgrep` filtered by `-x`/exact pattern, or a script file.
