# hermes-icon

A cross-platform utility to customize the Hermes desktop application icon across every surface (source repository assets, compiled macOS `Assets.car`, `icon.icns`, Windows `icon.ico`, `app.asar` & `ElectronAsarIntegrity`, code signature, and web UI favicon) and automatically re-apply it after updates via `launchd` (macOS), Task Scheduler (Windows), and Git hooks.

## Features

- **9 Curated Presets**: Mirror-mosaic chrome portrait (`disco-girl`) plus 8 geometric vector emblems rendered in both light and dark squircle plates (`caduceus`, `winged-helmet`, `winged-sandal`, `monogram-h`, `neural-core`, `compass`, `terminal`, `shield`).
- **Custom Icon Support**: Use any `.svg`, `.png`, `.icns`, `.ico`, `.jpg`, or `.webp` file (with optional `--custom-dark`, `--scale`, `--full-bleed`, and `--bg-light`/`--bg-dark` plate colors).
- **Three Interfaces**:
  - **CLI** (`hermes-icon list`, `hermes-icon set ...`, `hermes-icon status`)
  - **Interactive Terminal Picker (TUI)** (`hermes-icon pick` or `hermes-icon` in a TTY) with live 24-bit color half-block previews and native file dialog (`f` via Finder on macOS or Explorer on Windows)
  - **Local Web GUI** (`hermes-icon gui`) with live light/dark squircle previews, drag-and-drop upload, color pickers, scale slider, and one-click Apply & Watch
- **Full Surface Replacement**:
  - Regenerates all 99 targets in your `hermes-agent` repository (`nous-girl-{black,white}.svg` compatible with `generate_icons.py --check`, PNG/ICO/ICNS/MSIX/Icon Composer assets), or stages targets under `icon-replacer/staged-repo` for standalone packaged desktop installs without a source checkout
  - Updates `hermes_cli/web_dist/favicon.ico` when present
  - **macOS**: Compiles macOS 26 `Assets.car` via `/usr/bin/actool`, replaces `icon.icns` / `icon.ico` / `app.asar.unpacked/dist/*`, patches `app.asar` & `Info.plist` (`ElectronAsarIntegrity`), re-signs `Hermes.app` with `/usr/bin/codesign`, and patches `/Applications/Hermes.app/Contents/Resources/icon.icns` when present and writable
  - **Windows**: Patches MSIX (`WindowsApps` / `Hermes Agent`) packages including all 62 Start Menu & Taskbar tile PNGs (`Square44x44Logo*`, `Square150x150Logo*`, `StoreLogo*`, `Wide310x150Logo*`), plus unpacked Electron directories (`win-unpacked`, `%LOCALAPPDATA%\Programs\Hermes Agent`, `%LOCALAPPDATA%\Programs\Hermes`, `%LOCALAPPDATA%\hermes-desktop`, `%ProgramFiles%\Hermes`) (`resources/icon.ico`, `resources/app.asar`, `resources/app.asar.unpacked/dist/*`), and refreshes the Windows shell/MSIX icon caches & `.lnk` shortcuts
- **Automatic Update Recovery**:
  - **macOS**: Installs a `launchd` agent (`WatchPaths` + 60s fingerprint check) and Git hooks (`post-merge`, `post-checkout`, `post-rewrite`)
  - **Windows**: Registers a `HermesIconReplacer` Task Scheduler job (60s check) and Git hooks so updates that restore the default icon re-apply your chosen icon automatically
- **Lossless Backup & Restore**:
  - Backs up original icons to `~/.hermes/icon-replacer/backups/original/` with a SHA-256 `manifest.json` on first run; run `hermes-icon restore` anytime to revert.

## Requirements

- **macOS** (tested on Apple Silicon with Xcode / `actool` and `codesign`), **Windows 10/11**, or **Linux**
- Python 3.11+ (`Pillow` and `resvg-py` are resolved automatically from your Hermes installation or bootstrapped automatically into `$HERMES_HOME/icon-replacer/.venv` on first run / `hermes-icon --bootstrap`)

## Installation

### macOS (Homebrew)

```bash
brew install bulyaki/tap/hermes-icon
```

or:

```bash
brew tap bulyaki/tap
brew install hermes-icon
```

### Windows (Scoop)

```powershell
scoop bucket add bulyaki https://github.com/bulyaki/scoop-bucket
scoop install hermes-icon
```

### Windows / macOS / Linux (`uv`)

```bash
uv tool install git+https://github.com/bulyaki/hermes-icon
```

### From Source

macOS / Linux:

```sh
git clone https://github.com/bulyaki/hermes-icon.git ~/Work/hermes-icon
mkdir -p ~/.local/bin ~/.hermes/bin
ln -sfn ~/Work/hermes-icon/bin/hermes-icon ~/.local/bin/hermes-icon
ln -sfn ~/Work/hermes-icon/bin/hermes-icon ~/.hermes/bin/hermes-icon
```

Windows (PowerShell):

```powershell
git clone https://github.com/bulyaki/hermes-icon.git "$HOME\Work\hermes-icon"
# Add $HOME\Work\hermes-icon\bin to your PATH to invoke hermes-icon.cmd
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
hermes-icon set disco-girl
hermes-icon set caduceus
hermes-icon set winged-helmet

# Apply a custom icon with optional dark variant and plate colors
hermes-icon set --custom ~/Pictures/my-icon.png --scale 0.80
hermes-icon set --custom ~/Pictures/logo.svg --bg-light '#f8fafc' --bg-dark '#111827'
hermes-icon set --custom C:\Icons\my-app.ico

# Check sync state across all tracked surfaces
hermes-icon status
hermes-icon check [--apply]

# Manage background watcher (launchd on macOS, Task Scheduler on Windows) and git hooks
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

Runtime configuration, backups, lockfiles, and logs are kept outside the source checkout in `%LOCALAPPDATA%\hermes\icon-replacer\` on Windows or `~/.hermes/icon-replacer/` on macOS/Linux (override with `HERMES_ICON_STATE_DIR`):

- `HERMES_HOME`: Base Hermes directory (default on Windows: `%LOCALAPPDATA%\hermes`, falling back to `%USERPROFILE%\.hermes` if present; default on macOS/Linux: `~/.hermes`)
- `HERMES_REPO`: Hermes repository path (default: `$HERMES_HOME/hermes-agent` or packaged `agent-payload/repo` when present)
- `HERMES_ICON_STATE_DIR`: Runtime state directory (default: `$HERMES_HOME/icon-replacer`)
- `HERMES_PYTHON`: Optional explicit Python interpreter path override

## License

MIT — see [LICENSE](LICENSE).
