# hanauta-plugin-vpn-control

Hanauta plugin repository for vpn control.

## Entrypoints
- hanauta_plugin.py (plugin metadata/registration when present)

## Usage
Install through Hanauta Marketplace or clone into your Hanauta plugins directory.

## Marketplace install (privileged)
When installed via Hanauta Marketplace, this plugin can run a Polkit (pkexec) step to install a root systemd service that auto-connects WireGuard at boot without prompting for a password.

- Unit: `hanauta-wireguard-autoconnect.service`
- Config: `/etc/hanauta-wireguard-autoconnect.conf` (sets `WG_IFACE=<your-interface>`)
- No interface name is assumed; select one in the plugin UI (or set `WG_IFACE` manually).

You can uninstall/revert it from the Marketplace uninstall flow (privileged uninstall).
