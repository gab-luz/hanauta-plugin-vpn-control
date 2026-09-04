# AGENTS.md - Hanauta VPN Control Plugin

## Project Overview
WireGuard control popup with split tunneling support for Hanauta desktop environment. Provides UI for managing WireGuard tunnels and per-app/per-domain routing via cgroups v2 + nftables.

## Architecture

### Core Components
```
hanauta-plugin-vpn-control/
├── vpn_control.py           # Main UI popup (PyQt6)
├── split_tunnel.py          # Split tunneling engine (cgroups, nftables, routing)
├── root_wireguard_agent.py  # Root service (systemd, manages WireGuard + split tunnel)
├── service_wireguard_cache.py  # Cache generator for UI
├── hanauta_plugin.py        # Hanauta settings integration
├── hanauta_bar_plugin.py    # Hanauta bar integration
├── i18n.py                  # Localization (gettext)
├── locales/                 # Translations (.po/.mo)
│   ├── en_US/
│   ├── pt_BR/
│   ├── ru_RU/
│   └── es_AR/
├── bin/
│   ├── install_root_service.sh
│   └── uninstall_root_service.sh
├── systemd/
│   └── hanauta-wireguard-agent.service
└── assets/                  # Icons
```

### Data Flow
```
UI (vpn_control.py) 
    ↔ IPC (request.json/response.json) 
    ↔ Root Agent (root_wireguard_agent.py) 
        ↔ WireGuard (wg-quick) 
        ↔ Split Tunnel Manager (split_tunnel.py)
            ├── CgroupManager     → /sys/fs/cgroup/hanauta-split-vpn
            ├── NftablesManager   → fwmark 0x800/0x801, masquerade, killswitch
            ├── ProcessMonitor    → /proc scan, matches executables + Flatpak
            ├── RoutingManager    → ip route host routes (VPN/direct)
            ├── HostRoutesManager → DNS-resolved routes tracking
            └── DnsResolver       → async DNS resolution (300s default)
```

## Development Setup

### Prerequisites
- Python 3.10+
- PyQt6
- WireGuard tools (`wg-quick`, `ip`, `nft`)
- cgroups v2 mounted (`/sys/fs/cgroup`)
- systemd

### Package Management (uv)
```bash
# Install uv if not available
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
uv pip install -e ".[dev]"

# Or for production
uv pip install -e .
```

### Running Locally
```bash
# From project root
cd hanauta-plugin-vpn-control
uv run python vpn_control.py
```

### Install Root Service (requires sudo/pkexec)
```bash
./bin/install_root_service.sh
```

## Code Conventions

### Python Style
- Type hints required (`from __future__ import annotations`)
- Dataclasses for config objects
- Centralized logging via `append_log()`
- No bare `except:` - always specify exception type
- Async/await for DNS resolution, threading for process monitoring

### IPC Protocol (request.json/response.json)
```json
{
  "request_id": "uuid",
  "action": "toggle|list_interfaces|set_interface|enable_split_tunnel|disable_split_tunnel|set_split_config|get_split_status|on_tunnel_connected|on_tunnel_disconnected",
  "interface": "wg0",
  "config": { ... }
}
```

### Split Tunnel Config Schema
```json
{
  "enabled": false,
  "mode": "inclusive",
  "kill_switch": false,
  "apps_vpn": ["/usr/bin/firefox"],
  "apps_direct": ["/usr/bin/steam"],
  "domains_vpn": ["company.internal"],
  "domains_direct": ["netflix.com"],
  "resolve_interval_secs": 300,
  "default_route_vpn": true
}
```

### Settings (settings.json)
```json
{
  "services": {
    "vpn_control": {
      "enabled": true,
      "preferred_interface": "wg0",
      "reconnect_on_login": false,
      "language": "pt_BR",
      "split_tunnel": { ... }
    }
  }
}
```

## Localization

### Adding Translations
1. Extract messages: `pygettext3 -o locales/vpn_control.pot vpn_control.py hanauta_bar_plugin.py hanauta_plugin.py`
2. Update .po files: `msgmerge -U locales/pt_BR/LC_MESSAGES/vpn_control.po locales/vpn_control.pot`
3. Translate in .po files (use msgctxt for disambiguation)
4. Compile: `msgfmt locales/pt_BR/LC_MESSAGES/vpn_control.po -o locales/pt_BR/LC_MESSAGES/vpn_control.mo`

### Supported Languages
- `en_US` - English (US) - default
- `pt_BR` - Portuguese (Brazil)
- `ru_RU` - Russian
- `es_AR` - Spanish (Argentina)

### Context Usage
```python
# Same English string, different contexts
_("Add app to VPN list")      # msgctxt "vpn_list_button"
_("Add app to bypass list")   # msgctxt "bypass_list_button"
```

## Systemd Service

### Capabilities Required
```ini
CapabilityBoundingSet=CAP_NET_ADMIN CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_SYS_RESOURCE
AmbientCapabilities=CAP_NET_ADMIN CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_SYS_RESOURCE
```

| Capability | Purpose |
|------------|---------|
| CAP_NET_ADMIN | nftables, ip route, ip rule |
| CAP_SYS_ADMIN | cgroups v2 (mkdir, write cgroup.procs) |
| CAP_DAC_OVERRIDE | read /proc/*/exe, /proc/*/cmdline |
| CAP_SYS_RESOURCE | override resource limits |

## Testing Checklist

### Before Commit
- [ ] `python3 -m py_compile *.py` passes
- [ ] `msgfmt --check locales/*/LC_MESSAGES/vpn_control.po` passes
- [ ] UI launches without errors
- [ ] Split tunnel config persists across restarts

### Manual Testing
- [ ] Toggle WireGuard on/off
- [ ] Add/remove apps in VPN/direct lists
- [ ] Add/remove domains in VPN/direct lists
- [ ] Switch inclusive/exclusive mode
- [ ] Enable/disable kill switch
- [ ] Language change persists
- [ ] Root install script runs via pkexec

## Common Issues

| Issue | Solution |
|-------|----------|
| "cgroup.procs not found" | Ensure cgroups v2 mounted: `mount | grep cgroup` |
| "nftables not found" | Install `nftables` package |
| "pkexec not available" | Install `polkit` |
| UI doesn't show split tunnel status | Check root agent is running: `systemctl status hanauta-wireguard-agent` |
| Translations not loading | Verify .mo files exist in locales/*/LC_MESSAGES/ |

## Key Files to Know

| File | Purpose |
|------|---------|
| `split_tunnel.py` | All split tunneling logic |
| `root_wireguard_agent.py` | Root service entry point + IPC |
| `vpn_control.py` | Full UI with split tunnel config |
| `i18n.py` | Localization system |
| `systemd/hanauta-wireguard-agent.service` | Systemd unit with capabilities |
| `bin/install_root_service.sh` | Installation script (run via pkexec) |

## Git Workflow
```bash
# Standard workflow
git add .
git commit -m "type: description"
git push
```

### Commit Types
- `feat:` - new feature
- `fix:` - bug fix
- `refactor:` - code restructuring
- `i18n:` - translation updates
- `docs:` - documentation changes