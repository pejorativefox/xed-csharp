# xed-csharp — C# DevKit-like plugin for xed (Linux Mint)

Single multi-feature Python plugin (`Loader=python3`):

- **Solution Explorer** (side panel): `.sln/.slnx` discovery via upward search,
  projects via `dotnet sln list` with glob fallback, `.cs` quick navigation,
  right-click Build / Run / Test / Debug per project.
- **Test Explorer** (side panel): per-project discovery via
  `dotnet test --list-tests`, Run All / per-test runs with `--filter`, outcome
  glyphs (✓/✗/○) parsed from console output (xUnit/NUnit/MSTest tolerant).
- **Build output + Problems** (bottom panel): streaming `dotnet` output plus a
  clickable Problems list (diagnostics, definitions, references).
- **Roslyn intelligence**: stdio LSP client talking to `roslyn-language-server`
  (`~/.dotnet/tools/roslyn-language-server`, v5.9.0 verified). Standard
  `initialize` → `initialized` + Roslyn `solution/open` quirk,
  `didOpen`/`didChange` (debounced per view) / `didSave` / `didClose`.
  - Completion via the editor's own completion window (same framework as
    the bundled Word Completion plugin: interactive on typing, `Ctrl+Space`
    on demand, `Tab`/`Enter` accepts). A custom popup remains as fallback
    on builds without GtkSource.
  - Hover tooltips, Go to Definition (`F12`), Find References (`Shift+F12`),
    Format Document (`Shift+Alt+F`, optional format-on-save), Quick Fix menu
    (`Alt+Enter`, incl. `codeAction/resolve` + `workspaceEdit` support).
  - Diagnostics rendered as editor underline tags + gutter marks, mirrored to
    Problems + status line.
- **Debugging** (bottom panel): F9 toggles persistent breakpoints (gutter marks),
  F5 builds the startup project and launches it under `netcoredbg` via a minimal
  DAP client (same Content-Length framing as LSP). Call stack, scopes/variables,
  Continue / Step Over / Into / Out / Stop. Missing `netcoredbg` degrades to an
  install hint instead of silent failure.

Additional standalone plugins:

- **project-mode** (side panel): language-agnostic folder browser opened with
  `Ctrl+Shift+O`; selecting a folder renders its file tree on the left and row
  activation opens files in xed.
- **feature-toggle**: hides xed's built-in Documents list and closes the lone
  untouched "Unsaved Document 1" starter tab on startup (both enabled by
  default, configurable via INI).

## Shortcuts (in C# files)

| Keys | Action |
| ---- | ------ |
| `Ctrl+Space`, `.`, `(` | Completion |
| `F12` / `Shift+F12` | Go to Definition / Find References |
| `Alt+Enter` | Quick Fix… |
| `Shift+Alt+F` | Format Document |
| `F9` | Toggle breakpoint |
| `F5` | Debug startup project |

## Global shortcuts (Panel Hider plugin)

| Keys | Action |
| ---- | ------ |
| `Ctrl+B` | Hide side + bottom panes |
| `Ctrl+J` | Toggle bottom pane |
| `Ctrl+E` | Toggle side pane |

## Global shortcuts (project-mode plugin)

| Keys | Action |
| ---- | ------ |
| `Ctrl+Shift+O` | Choose folder root for file tree |

## Layout

```
plugins/
  panel-hider/
    panel-hider.plugin
    panelhider/
      __init__.py       # global pane hide/toggle shortcuts
  feature-toggle/
    feature-toggle.plugin
    featuretoggle/
      __init__.py       # hide Documents panel + close untouched starter tab
  project-mode/
    project-mode.plugin
    projectmode/
      __init__.py       # folder browser side panel + Ctrl+Shift+O
  xedcsharp/
    xedcsharp.plugin    # Loader=python3, Module=xedcsharp, IAge=3
    xedcsharp/
      __init__.py       # Xed.WindowActivatable entry + wiring
      views.py          # per-view tracker (sync, keys, menu, hover)
      gscompletion.py   # Roslyn GtkSource.CompletionProvider (preferred)
      completion.py     # completion popup (pure Gtk3, fallback only)
      explorer.py       # solution explorer (side)
      testpanel.py      # test explorer (side)
      output.py         # output + problems (bottom)
      debugpanel.py     # breakpoints/stack/variables (bottom)
      solution.py       # sln/csproj discovery (no MSBuild parser)
      dotnet_cli.py     # sync + streaming runners (headless-testable)
      lsp_transport.py  # Content-Length JSON-RPC over stdio
      roslyn.py         # Roslyn lifecycle + handshake
      dap.py            # minimal DAP client for netcoredbg
      breakpoints.py    # persistent breakpoint store
      intelligence.py   # positions, completion/hover/location/edit helpers
      testing.py / debugging.py
      settings.py       # INI store, no GSettings schema
tests/                  # headless unit tests (no GTK, no pytest needed)
```

## Install

```bash
./install.sh
# restart xed, enable the plugins you want in Preferences -> Plugins
XED_PLUGIN_DEBUG=1 xed   # debug logs to stderr
```

Requires: `xed 3.x`, `python3-gi`, `dotnet` SDK 9/10,
`dotnet tool install --global roslyn-language-server`.
Optional: `netcoredbg`, `ctags`, `ripgrep`.

## Verify

```bash
python3 -m pytest tests/ -q
# or without pytest: python3 -c "<loader>" (see CI)
```

## Troubleshooting (no signs of life?)

```bash
python3 doctor.py   # checks install, GI plumbing, toolchain, xed state
```

Known causes, in order of likelihood:

1. **Stale xed process.** `xed` is a single-instance GApplication: running
   `XED_PLUGIN_DEBUG=1 xed` while xed is already open just pings the old
   process — the env var never arrives and stderr goes nowhere useful.
   Fully quit first (File → Quit all windows), then `XED_PLUGIN_DEBUG=1 xed`.
2. **Side/bottom panes hidden.** New panels land in xed's side/bottom panes;
   show them via View → Side Pane / Bottom Pane.
3. **Private typelib paths.** Some builds install `Xed-1.0.typelib` and
   `libxed.so` outside the standard search paths, which silently breaks
   *every* Python plugin (`ValueError: Namespace Xed not available`). The
   plugin self-registers xed's private dirs at import; if import still fails,
   the full traceback now goes to stderr instead of failing silently.
4. **Proof of life.** With `XED_PLUGIN_DEBUG=1`, the plugin appends to
   `/tmp/xedcsharp-<uid>.log` on import and activation — check it even when
   stderr is swallowed (desktop-menu launches log to the journal).
5. **Roslyn server deaths.** The C# Output panel now shows the exit code plus
   the server's own error lines, and the full stderr is kept at
   `~/.cache/xed/xed-csharp/roslyn-logs/roslyn-stderr.log`. After a crash,
   C# Solution → Refresh restarts the server.

## Design notes

- xed 3.8 has no LSP client, so the plugin owns background reader threads and
  marshals callbacks via `GLib.idle_add` (see `RoslynManager(ui_dispatch=…)`
  and `DapSession`).
- Completion registers a `GtkSource.CompletionProvider` on every view,
  exactly like the bundled Word Completion plugin does, so the editor's
  own completion window handles focus, filtering and commit (a custom
  pure-Gtk3 popup in `completion.py` remains as fallback for builds
  without the GtkSource typelib).
- Settings live in `~/.config/xed/plugins/xed-csharp/settings.ini`;
  breakpoints in `breakpoints.ini` alongside.
