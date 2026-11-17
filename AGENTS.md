# Agent notes

- **Debugging on the Frame:** read [docs/debugging-the-frame.md](docs/debugging-the-frame.md)
  first. You have the device and the permission; do the work yourself and prove it with
  automation. Do not ask the user to move the headset or run things you can run.
- Logs and diagnostics: [docs/runbook-logs.md](docs/runbook-logs.md).
- Tests: `python3 -m unittest discover -s tests -v` (Python 3.12+).
- The user dislikes lazy, give-up, wait-for-a-human behaviour. Research, try
  alternatives, then report results with evidence.
