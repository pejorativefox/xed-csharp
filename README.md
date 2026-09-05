# xed-csharp — turn xed into a lightweight code editor

A set of plugins that gives Linux Mint's xed editor some modern comforts:
a project file browser with git colors, quick file opening, C# support
with completions, git change markers in the editor gutter,
a built-in terminal, and handy shortcuts for hiding panes.

You don't need to know any programming to use these — install, enable,
and edit.

## What you get

**Project folder browser** (project-mode)
- Open any folder and browse its files in the side panel.
- Files are colored by git state, like in VS Code: green means new,
  tan means changed, red means deleted.
- Open a folder with `Ctrl+Shift+O`, or straight from the terminal:
  `xed-code [folder]` works like `code .` and opens the folder in a
  new xed window.

**Quick file opener** (fuzzy-finder)
- Press `Ctrl+P`, start typing any part of a file name, and jump to it.
  It understands capitals (`mc` finds `MyClass.cs`) and multiple words.

**Git change markers** (git-inline-diff)
- The left edge of the editor shows what changed compared to git:
  green for added lines, tan for changed lines, red where lines were
  deleted. Untracked new files show all green. Marks refresh every
  time you save.

**C# support** (C# DevKit for xed)
- Solution explorer, build / run / test per project, a test list with
  pass/fail marks, clickable error list, code completions, hover help,
   go-to-definition (`F12`), find references (`Shift+F12`), formatting
   (`Shift+Alt+F`) and quick fixes (`Alt+Enter`).

**Built-in terminal** (tabbed-terminal)
- A terminal in xed's bottom panel, with tabs.

**Less clutter** (panel-hider + feature-toggle)
- `Ctrl+B` hides side and bottom panes for distraction-free editing,
  `Ctrl+J` / `Ctrl+E` toggle bottom / side pane alone.
- Hides the built-in Documents list and closes the empty
  "Unsaved Document 1" tab xed starts with (both can be switched back
  off in the settings file if you miss them).

**Small helpers**
- `xed-open 'file.cs:line:col'` opens a file at an exact position —
  handy for terminal links.
- Two extra dark-friendly color schemes are installed automatically.

## Install

You need: **xed 3.x**, **python3-gi**, and for C# features the
**dotnet SDK** plus the Roslyn language server:

```bash
dotnet tool install --global roslyn-language-server
```

Then install everything:

```bash
./install.sh
```

Now **fully quit xed** (File → Quit all windows — important, see below),
start it again, and enable what you want under
Edit → Preferences → Plugins:
C# DevKit for xed, project-mode, fuzzy-finder, feature-toggle,
panel-hider, tabbed-terminal, git-inline-diff.

## Everyday shortcuts

| Keys | What it does |
| ---- | ------------ |
| `Ctrl+Shift+O` | Open a project folder |
| `Ctrl+P` | Quickly open any file in the project |
| `Ctrl+B` | Hide/show all panes (focus mode) |
| `Ctrl+J` / `Ctrl+E` | Toggle bottom / side pane |
| `Ctrl+Space` | Code completions (C#) |
| `F12` / `Shift+F12` | Go to definition / find references (C#) |
| `Alt+Enter` | Quick fix for the error at the cursor (C#) |
| `Shift+Alt+F` | Format the file (C#) |

## Something not working?

Run the self-check first:

```bash
python3 doctor.py
```

The usual culprits:

1. **xed was still running.** xed stays open in the background, so a new
   `xed` command just talks to the old one — new plugins and settings
   never load. Always use File → Quit all windows first, then start xed
   fresh.
2. **Panes are hidden.** New panels live in the side/bottom panes; turn
   them on via View → Side Pane / Bottom Pane.
3. **A plugin isn't enabled.** Check Edit → Preferences → Plugins.
4. **C# completions missing.** Make sure the dotnet SDK and
   `roslyn-language-server` are installed (see above). The C# Output
   panel at the bottom shows what the language server is doing.

If you report a problem, run `XED_PLUGIN_DEBUG=1 xed` from a terminal
(after fully quitting first) and include any lines starting with
`[project-mode]`, `[git-inline-diff]`, or `[xed-csharp]`.

## For developers

The test suite runs without pytest or a display — see `AGENTS.md` for
the exact command, plus contributor notes (plugin reinstall step,
diagnostics, and conventions).
