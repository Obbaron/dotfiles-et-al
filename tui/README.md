# dotfiles-tui

A two-panel TUI for editing the `config.toml` that drives `dotfiles-et-al`,
because editing TOML by hand was apparently a bridge too far. Built with
[Textual](https://textual.textualize.io/) and
[tomlkit](https://github.com/python-poetry/tomlkit).

- **Spec-aware**: the forms know what a valid item looks like, so you don't have to.
- **Comment-preserving**: your ASCII art survives. This was non-negotiable.
- **Previewable**: the right panel shows what you're about to do before you do it.
- **Non-destructive**: it edits the config. Applying it remains someone else's problem.

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

Given no path, it resolves one in this order:

1. `$XDG_CONFIG_HOME/dotfiles-et-al/config.toml` — the live config `configure.py` seeded.
2. `./config.toml` — the repo template, if you're standing in the repo root.

---

## Interface

One screen, two panels, no floating dialogs. Everything happens where you're
already looking.

- **Left**: the list you navigate. Starts at *Sections* (profiles, then the eight
  steps) and descends into a profile's refs, a module's items, and onward. A
  divider separates profiles from steps, on the theory that they are not the same
  kind of thing.
- **Right**: a read-only preview of whatever the cursor is on — a section's
  modules, a profile's refs expanded to what they actually resolve to, a module's
  requires and items, or one item's fields.

Control lives in the left list. `enter`/`l` descends (the preview becomes the new
list); `escape`/`h` ascends and puts the cursor back where you left it. The
status line shows where you are; the footer shows the keys that work here.

The editing surfaces:

- **Item form** — replaces the preview panel. Fields follow the spec's item
  shapes: required fields, octal-mode checks, `content`/`source` mutual
  exclusion, tri-state `enabled`/`started`, an XDG label picker, `copy`/`sudo`
  switches. Forms emit the *minimal* shape: a packages item with no alias saves
  as a bare string, and a service with `scope = "system"` doesn't bother saying so.
- **Ref picker** — a two-panel takeover for a profile's refs or a module's
  `requires`. Toggleable list on the left; on the right, a live preview of what
  the highlighted ref resolves to, so the `*` wildcard holds no surprises.
  Selecting a `*.name` wildcard hides its member modules, since they are already
  covered; unselecting brings them back.
- **Command line** — a vim-style line at the bottom for names, delete
  confirmations (`y`/`esc`), and the three-way quit prompt you get when there are
  unsaved changes.
- **Validation** — a popup (`v`) listing every spec violation, by location.

---

## What it does

- **Browse** profiles and all eight steps (`packages` → … → `commands`) as a
  navigable tree with live preview.
- **Edit, add, and delete items** in a module through the item form.
- **Edit a profile's refs** and a module's **`requires`** through the ref picker,
  wildcards included.
- **Manage profiles and modules**: create, rename, delete.
- **Validate** the whole file against the spec checklist on demand, with
  per-location reporting. Saving with issues still saves — it's your file — but it
  will say something first.
- **Save preserving comments**: the ASCII-art header, the section comments, and
  every line you didn't touch survive byte-for-byte; only what you edited changes.
  Writes are atomic (temp file, then rename). New tables adopt the file's
  `{ key = value }` inline style.
- **Themes** from the command palette, remembered across runs (default:
  `catppuccin-mocha`), because a config editor with poor color discipline cannot
  be trusted with your config.

### Keys

Two key sets are live at once: **native** (arrows and ctrl-chords, advertised in
the footer) and **vim** (hjkl and single letters, not advertised, because you
already knew). Both are remappable.

| Action              | Native            | Vim               |
|---------------------|-------------------|-------------------|
| Move up / down      | `↑` / `↓`         | `k` / `j`         |
| First / last        | `home` / `end`    | `g` / `G`         |
| Page up / down      | `pageup`/`pagedn` | `ctrl+u`/`ctrl+d` |
| Open / descend      | `enter`, `→`      | `l`               |
| Back / ascend       | `escape`, `←`     | `h`               |
| Edit (refs / item)  | `e`               | `e`               |
| New                 | `ctrl+n`          | `n`               |
| Rename / requires   | `ctrl+r`          | `r`               |
| Delete              | `delete`          | `d`               |
| Save                | `ctrl+s`          | `w`               |
| Validate            | `ctrl+v`          | `v`               |
| Quit                | `ctrl+q`          | `q`               |
| Command palette     | `ctrl+p`          | `:`               |

In the ref picker, `space` (or `l`) toggles the highlighted ref and `enter`
accepts. The command palette lists everything, each entry prefixed with its
vim-ex-style shortcut (`w — Save`, `q — Quit`, `t — Theme`, …).

---

## Configuration

Both files live under `$XDG_CONFIG_HOME/dotfiles-et-al/` (typically
`~/.config/dotfiles-et-al/`), next to the `config.toml` you're editing.

- **`keybinds.toml`** overrides either key set. See
  [`keybinds.example.toml`](keybinds.example.toml) for every action id and its
  default. Only the keys you name change; an unknown id is reported rather than
  treated as a capital offense.

  ```toml
  [vim]
  "browse.last" = "dollar_sign"    # make $ jump to the last row

  [native]
  "global.save" = "ctrl+w"
  ```

- **`tui-settings.toml`** is written for you, to remember the theme and friends.
  Editing it by hand rather defeats the purpose.

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

- `spec.py` is UI-free and importable on its own, so a headless
  `python -c "…validate_config…"` linter falls out of it at no extra charge.
- `store.py` never rewrites the document wholesale; it touches only the arrays and
  keys you touched. This is the entire reason your comments still exist.

---

## Fine print

- **It edits; it does not apply.** Nothing here touches your machine. Re-run
  `./bootstrap.sh <profile>` for that, and for the consequences.
- **The spec is the arbiter.** The forms will not stop you from declaring a
  service on a host without systemd; they will only stop you from misspelling it.
- **Validation is advisory.** Saving an invalid config is permitted, on the
  grounds that it is your config and you may have plans.