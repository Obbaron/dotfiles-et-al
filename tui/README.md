# dotfiles-tui

Two-panel TUI editor for `config.toml` that drives `dotfiles-et-al`, built with
[Textual](https://textual.textualize.io/) and
[tomlkit](https://github.com/python-poetry/tomlkit).

---

## Install and run

Requires Python ≥ 3.11.

**uv:**

```sh
cd tui
uv run tui                    # edits your live per-machine config
uv run tui ../config.toml     # or edit the repo template
```

**pip:**

```sh
cd tui
pip install .
tui [path/to/config.toml]
```

The console script is named `tui`; `bootstrap.sh edit` invokes it via `edit.py`.

**Config resolution** when no path is given:

1. `$XDG_CONFIG_HOME/dotfiles-et-al/config.toml` (the live config seeded by
   `configure.py`)
2. `./config.toml` (the repo template, when run from the repo root)

---

## Interface

A single screen, two panels:

- **Left**: the list you navigate. It starts at *Sections* (profiles, then the
  eight steps), and descends into a profile's refs, a module's items, and so on.
  A divider separates profiles from the steps, since profiles are the
  higher-level grouping.
- **Right**: a read-only **preview** of whatever the cursor is on: a section's
  modules, a profile's refs expanded to what they resolve to, a module's
  requires and items, or a single item's fields.

Control lives in the left list; `enter`/`l` descends (the preview becomes the
new list), `escape`/`h` ascends and restores the cursor to where you were. The
bottom-left status line shows the current path; the footer shows the keys for
the current level.

Editing surfaces stay in-place rather than as floating dialogs:

- **Item form**: replaces the preview panel. Fields follow the spec's item
  shapes: required fields, octal-mode checks, `content`/`source` mutual
  exclusion, tri-state `enabled`/`started`, XDG label picker, `copy`/`sudo`
  switches. Forms emit the *minimal* shape — a packages item with no alias
  saves as a bare string; a service with `scope = "system"` omits the default.
- **Ref picker**: a two-panel takeover for a profile's refs or a module's
  `requires`: a toggleable list on the left, and a live preview on the right of
  the module(s) the highlighted ref resolves to, so you see what you're about
  to add. Selecting a `*.name` wildcard hides its member modules (they're
  redundant while the wildcard covers them); unselecting brings them back.
- **Command line**: a vim-style line at the bottom for names (new/rename),
  delete confirmations (`y`/`esc`), and the three-way quit prompt when there are
  unsaved changes.
- **Validation**: a popup (`v`) reporting any spec violations per location.

## What it does

- **Browse** profiles and all eight steps (`packages` → … → `commands`) as a
  navigable tree with live preview.
- **Edit, add, and delete items** within a module through the item form.
- **Edit a profile's refs** and a **module's `requires`** through the ref
  picker, including `*.name` wildcards for names defined under several steps.
- **Manage profiles and modules**: create, rename (profiles), and delete.
- **Validate** the whole file against the spec checklist at any time, with
  per-location issue reporting. Saving with issues still saves (it's your file)
  but warns.
- **Save preserving comments**: the ASCII-art header, section comments, and
  untouched lines survive byte-for-byte; only edited entries change. Writes are
  atomic (temp file + rename). New tables use the file's `{ key = value }`
  inline style.
- **Themes** switch from the command palette; the choice persists across runs
  (default: `catppuccin-mocha`). The whole UI follows the active theme.

### Keys

Two key sets are active at once: **native** (arrows and ctrl-chords, shown in
the footer) and **vim** (hjkl and single letters). Both are remappable; see
*Configuration* below.

| Action              | Native            | Vim            |
|---------------------|-------------------|----------------|
| Move up / down      | `↑` / `↓`         | `k` / `j`      |
| First / last        | `home` / `end`    | `g` / `G`      |
| Page up / down      | `pageup`/`pagedn` | `ctrl+u`/`ctrl+d` |
| Open / descend      | `enter`, `→`      | `l`            |
| Back / ascend       | `escape`, `←`     | `h`            |
| Edit (refs / item)  | `e`               | `e`            |
| New                 | `ctrl+n`          | `n`            |
| Rename / requires   | `ctrl+r`          | `r`            |
| Delete              | `delete`          | `d`            |
| Save                | `ctrl+s`          | `w`            |
| Validate            | `ctrl+v`          | `v`            |
| Quit                | `ctrl+q`          | `q`            |
| Command palette     | `ctrl+p`          | `:`            |

In the ref picker, `space` (or `l`) toggles the highlighted ref and `enter`
accepts. The command palette lists everything, each entry prefixed with its
vim-ex-style shortcut (`w — Save`, `q — Quit`, `t — Theme`, …).

---

## Configuration

Both files live under `$XDG_CONFIG_HOME/dotfiles-et-al/` (typically
`~/.config/dotfiles-et-al/`), alongside the `config.toml` you're editing.

- **`keybinds.toml`** overrides both key sets. See
  [`keybinds.example.toml`](keybinds.example.toml) for the full list of action
  ids and defaults. Only the keys you name change; unknown ids are reported, not
  fatal.

  ```toml
  [vim]
  "browse.last" = "dollar_sign"    # make $ jump to the last row

  [native]
  "global.save" = "ctrl+w"
  ```

- **`tui-settings.toml`** is written automatically to remember settings, theme, etc.

---

## Layout

```
tui/
├── pyproject.toml          # deps, entry point (tui), dev extras
├── keybinds.example.toml   # copyable reference for keybinds.toml
├── config_tui/
│   ├── __main__.py         # CLI: path resolution, load, run
│   ├── spec.py             # schema knowledge + validation (from the spec)
│   ├── store.py            # tomlkit load/edit/save, comment-preserving
│   ├── keymap.py           # dual native/vim key sets, user remapping
│   ├── settings.py         # persisted UI prefs (theme)
│   └── ui.py               # the two-panel app: screens, navigation, editors
└── tests/                  # pytest: spec, store, settings, Pilot UI tests
```

- `spec.py` is UI-free and importable on its own: headless
  `python -c "…validate_config…"` linter falls out of it for free.
- `store.py` never rewrites the document wholesale; it mutates only the
  arrays/keys you touch, which is what keeps comments intact.
