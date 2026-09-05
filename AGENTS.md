# AGENTS.md — xed-csharp contributor notes

## After ANY code change: reinstall the plugin

```bash
./install.sh
```

`xed` loads the plugin from `~/.local/share/xed/plugins/`, **not** from this
repo. If you skip this, xed keeps running the old copy and your fix will look
like it did nothing. Then fully quit xed (File → Quit all windows —
single-instance reuse keeps the old process *and* its working directory) and:

```bash
XED_DEBUG_CSHARP=1 xed
```

## Tests (no pytest in this env)

```bash
python3 -c "import os,glob; d='tests'; files=sorted(glob.glob(d+'/test_*.py')); import importlib.util; fails=0; total=0
for f in files:
    name=f.replace('/','_').replace('.py','')
    spec=importlib.util.spec_from_file_location(name,f); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    for a in dir(m):
        if a.startswith('test_'):
            total+=1
            try: getattr(m,a)()
            except Exception as e: fails+=1; print(f'FAIL {f}:{a}: {e!r}')
print(f'{total-fails}/{total} passed')"
```

Note: `tests/test_completion_popup.py::test_focus_stays_in_editor_through_show_nav_filter`
is a pre-existing GUI-focus flake that fails headless (fails on clean tree too).

## Diagnose

- `python3 doctor.py` — install, GI plumbing, toolchain, xed state.
- Marker log `/tmp/xedcsharp-$(id -u).log` — proof of load/activate.
- C# Output bottom panel — `Roslyn starting/ready` lines and server exit codes.
- Server stderr: `~/.cache/xed/xed-csharp/roslyn-logs/roslyn-stderr.log`.

## Conventions

- Startup/dependency problems are **soft-only**: log via `logging_util.error()`
  (always writes to stderr + marker log), never raise. `debug()` is gated behind
  `XED_DEBUG_CSHARP` — don't use it for anything the user must see.
- Keep `xedcsharp/{solution,dotnet_cli,roslyn,deps,intelligence}.py` headless-safe
  (no GTK imports) so unit tests run without a display.
- Never hand Roslyn a broad workspace root (`$HOME`, `/`): it crawls symlinks
  (e.g. Wine `dosdevices/z:` → `/proc`) and aborts. See `is_home_root()` and the
  fallback-walk guards in `solution.py`.
