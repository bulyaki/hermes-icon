# hermes-icon

A macOS utility to customize the Hermes desktop application icon across every surface (source repository assets, compiled macOS `Assets.car`, `icon.icns`, `app.asar` & `ElectronAsarIntegrity`, code signature, and web UI favicon) and automatically re-apply it after updates via `launchd` and Git hooks.

## Features

- **9 Curated Presets**: Mirror-mosaic chrome portrait (`disco-girl`) plus 8 geometric vector emblems rendered in both light and dark squircle plates (`caduceus`, `winged-helmet`, `winged-sandal`, `monogram-h`, `neural-core`, `compass`, `terminal`, `shield`).
- **Custom Icon Support**: Use any `.svg`, `.png`, `.icns`, `.jpg`, or `.webp` file (with optional `--custom-dark`, `--scale`, `--full-bleed`, and `--bg-light`/`--bg-dark` plate colors).
- **Three Interfaces**:
  - **CLI** (`hermes-icon list`, `hermes-icon set ...`, `hermes-icon status`)
  - **Interactive Terminal Picker (TUI)** (`hermes-icon pick` or `hermes-icon` in a TTY) with live 24-bit color half-block previews and native macOS Finder file dialog (`f`)
  - **Local Web GUI** (`hermes-icon gui`) with live light/dark squircle previews, drag-and-drop upload, color pickers, scale slider, and one-click Apply & Watch
- **Full Surface Replacement**:
  - Regenerates all 99 targets in `~/.hermes/hermes-agent` (`nous-girl-{black,white}.svg` compatible with `generate_icons.py --check`, PNG/ICO/ICNS/MSIX/Icon Composer assets)
  - Updates `~/.hermes/hermes-agent/hermes_cli/web_dist/favicon.ico`
  - Compiles macOS 26 `Assets.car` via `/usr/bin/actool`, replaces `icon.icns` / `icon.ico` / `app.asar.unpacked/dist/*`, patches `app.asar` & `Info.plist` (`ElectronAsarIntegrity`), and re-signs `Hermes.app` with `/usr/bin/codesign`
  - Patches `/Applications/Hermes.app/Contents/Resources/icon.icns` when present and writable
- **Automatic Update Recovery**:
  - Installs a `launchd` agent (`WatchPaths` + 60s fingerprint check) and Git hooks (`post-merge`, `post-checkout`, `post-rewrite`) that detect when `hermes update` restores the default icon and re-apply your chosen icon automatically.
- **Lossless Backup & Restore**:
  - Backs up original icons to `~/.hermes/icon-replacer/backups/original/` with a SHA-256 `manifest.json` on first run; run `hermes-icon restore` anytime to revert.

## Requirements

- macOS (tested on Apple Silicon with Xcode / `actool` and `codesign`)
- An active Hermes installation under `~/.hermes/installs/` (resolved automatically via `facts.json` for `Pillow` and `resvg_py`)

## Installation

### Homebrew (Recommended)

```bash
brew install bulyaki/tap/hermes-icon
```

or:

```bash
brew tap bulyaki/tap
brew install hermes-icon
```

### From Source

```sh
git clone https://github.com/bulyaki/hermes-icon.git ~/Work/hermes-icon
mkdir -p ~/.local/bin ~/.hermes/bin
ln -sfn ~/Work/hermes-icon/bin/hermes-icon ~/.local/bin/hermes-icon
ln -sfn ~/Work/hermes-icon/bin/hermes-icon ~/.hermes/bin/hermes-icon
```

Activate the background watcher:

```sh
hermes-icon watch install
```

## Usage

```sh
# Launch the interactive terminal picker
hermes-icon pick

# Launch the visual local web GUI picker
hermes-icon gui

# List presets and current sync status
hermes-icon list

# Apply a built-in preset everywhere
hermes-icon set caduceus
hermes-icon set winged-helmet

# Apply a custom icon with optional dark variant and plate colors
hermes-icon set --custom ~/Pictures/my-icon.png --scale 0.80
hermes-icon set --custom ~/Pictures/logo.svg --bg-light '#f8fafc' --bg-dark '#111827'

# Check sync state across all tracked surfaces
hermes-icon status
hermes-icon check [--apply]

# Manage launchd agent and git hooks
hermes-icon watch [install|uninstall|status|run]

# Restore original icons and pause the watcher
hermes-icon restore
```

## Presets

| ID | Name | Description |
| --- | --- | --- |
| `disco-girl` | Disco Nous | Mirror-mosaic chrome portrait on transparent background (default) |
| `caduceus` | Hermes Caduceus | Classic winged staff with twin serpents |
| `winged-helmet` | Hermes Petasos | Winged traveler's helmet with arched brim |
| `winged-sandal` | Talaria Wing | Classic winged Greek sandal emblem |
| `monogram-h` | Geometric H Monogram | Architectural `H` in an octagonal frame |
| `neural-core` | Orbital Constellation | Central hub & hexagonal orbital lattice |
| `compass` | Wayfinder Compass | Precision 8-point navigational compass |
| `terminal` | Developer Terminal | Command prompt `>_` in a rounded frame |
| `shield` | Aegis Crest | Layered shield crest with chevron insignia |

## Runtime State & Environment Variables

Runtime configuration, backups, lockfiles, and logs are kept outside the source checkout in `~/.hermes/icon-replacer/` (override with `HERMES_ICON_STATE_DIR`):

- `HERMES_HOME`: Base Hermes directory (default: `~/.hermes`)
- `HERMES_REPO`: Hermes repository path (default: `$HERMES_HOME/hermes-agent`)
- `HERMES_ICON_STATE_DIR`: Runtime state directory (default: `$HERMES_HOME/icon-replacer`)

## License

MIT — see [LICENSE](LICENSE).
