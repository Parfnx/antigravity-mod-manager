# Antigravity Mod Manager (Unified Patcher)

Single-pass installer and update-recovery manager for Antigravity sidebar extensions (`fast-switch`, `mcp-panel`, `context-panel`).

## Features
- Applies any combination of modules in a single `app.asar` repack pass (no repeated backups or broken markers).
- Preserves `antigravity-ascii-wallpapers` automatically if installed.
- Tracks active modules and `app.asar` SHA-256 in `~/.gemini/antigravity/mod-manager.json` so you can re-apply everything in one command after Antigravity auto-updates.
- Verifies SHA-256 integrity and syntax (`node --check`) before touching the live `app.asar`.

## Supported Modules
- `fast-switch` — Google account switcher ([antigravity-fast-switch](https://github.com/Parfnx/antigravity-fast-switch))
- `mcp-panel` — Active MCP servers monitor & toggle ([antigravity-mcp-panel](https://github.com/Parfnx/antigravity-mcp-panel))
- `context-panel` — Cascade memories, rules, skills, and workflows manager ([antigravity-context-panel](https://github.com/Parfnx/antigravity-context-panel))

## Requirements
- Windows 10/11
- Python 3
- Node.js (`node --check`)
- Git (for fetching module repos if not already present locally)

## Usage
```powershell
git clone https://github.com/Parfnx/antigravity-mod-manager.git
cd antigravity-mod-manager
powershell -ExecutionPolicy Bypass -File .\manage.ps1
```

### Non-interactive CLI
```powershell
# Check status and detect Antigravity auto-updates
python .\mod_manager.py status

# Apply all modules
powershell -ExecutionPolicy Bypass -File .\manage.ps1 -Action apply -Mods fast-switch,mcp-panel,context-panel

# Re-apply saved profile after an Antigravity update
powershell -ExecutionPolicy Bypass -File .\manage.ps1 -Action reapply

# Restore original backup
powershell -ExecutionPolicy Bypass -File .\manage.ps1 -Action restore
```
