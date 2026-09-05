# AGENTS.md — xed-csharp contributor notes

## After ANY code change: reinstall the plugin

```bash
./install.sh
```

`xed` loads the plugin from `~/.local/share/xed/plugins/xedcsharp/`, **not**
from this repo. If you skip this, xed keeps running the old copy and your fix
will look like it did nothing. Then fully quit xed (File → Quit all windows —
single-instance reuse keeps the old process *and* its working directory) and:

```bash
XED_PLUGIN_DEBUG=1 xed
```

## Tests

```bash
python3 -m pytest -q
```

Headless; GUI tests report SKIPPED. Full suite including window-spawning
tests:

```bash
xvfb-run -a python3 -m pytest -q
```

Note: `tests/test_completion_popup.py::test_focus_stays_in_editor_through_show_nav_filter`
is expected to SKIP headless and PASS under `xvfb-run`.

## Diagnose

- `python3 doctor.py` — install, GI plumbing, toolchain, xed state.
- Marker log `/tmp/xedcsharp-$(id -u).log` — proof of load/activate.
- C# Output bottom panel — `Roslyn starting/ready` lines and server exit codes.
- Server stderr: `~/.cache/xed/xed-csharp/roslyn-logs/roslyn-stderr.log`.

## Conventions

- Startup/dependency problems are **soft-only**: log via `logging_util.error()`
  (always writes to stderr + marker log), never raise. `debug()` is gated behind
  `XED_PLUGIN_DEBUG` — don't use it for anything the user must see.
- Keep `plugins/xedcsharp/xedcsharp/{solution,dotnet_cli,roslyn,deps,intelligence}.py` headless-safe
  (no GTK imports) so unit tests run without a display.
- Never hand Roslyn a broad workspace root (`$HOME`, `/`): it crawls symlinks
  (e.g. Wine `dosdevices/z:` → `/proc`) and aborts. See `is_home_root()` and the
  fallback-walk guards in `solution.py`.
