#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CGNAME = "hanauta-split-vpn"
CGROUP_ROOT = "/sys/fs/cgroup"
FW_MARK = 0x800
FW_MARK_WG = 0x801
ROUTING_TABLE = 100
DEFAULT_RESOLVE_INTERVAL = 300


@dataclass
class SplitTunnelConfig:
    enabled: bool = False
    mode: str = "inclusive"
    kill_switch: bool = False
    apps_vpn: list[str] = field(default_factory=list)
    apps_direct: list[str] = field(default_factory=list)
    domains_vpn: list[str] = field(default_factory=list)
    domains_direct: list[str] = field(default_factory=list)
    resolve_interval_secs: int = DEFAULT_RESOLVE_INTERVAL
    default_route_vpn: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitTunnelConfig:
        return cls(
            enabled=data.get("enabled", False),
            mode=data.get("mode", "inclusive"),
            kill_switch=data.get("kill_switch", False),
            apps_vpn=data.get("apps", {}).get("vpn", []),
            apps_direct=data.get("apps", {}).get("direct", []),
            domains_vpn=data.get("domains", {}).get("vpn", []),
            domains_direct=data.get("domains", {}).get("direct", []),
            resolve_interval_secs=data.get("domains", {}).get("resolve_interval_secs", DEFAULT_RESOLVE_INTERVAL),
            default_route_vpn=data.get("default_route_vpn", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "kill_switch": self.kill_switch,
            "apps": {"vpn": self.apps_vpn, "direct": self.apps_direct},
            "domains": {
                "vpn": self.domains_vpn,
                "direct": self.domains_direct,
                "resolve_interval_secs": self.resolve_interval_secs,
            },
            "default_route_vpn": self.default_route_vpn,
        }

    def get_app_list(self) -> list[str]:
        if self.mode == "exclusive":
            return self.apps_direct
        return self.apps_vpn


def run_cmd(cmd: list[str], capture: bool = True, timeout: float = 10.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return result.returncode == 0, (out or err or ("ok" if result.returncode == 0 else "failed"))
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


class CgroupManager:
    def __init__(self):
        self.cgroup_path = f"{CGROUP_ROOT}/{CGNAME}"
        self.enabled = False

    def enable(self) -> tuple[bool, str]:
        path = Path(self.cgroup_path)
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created cgroup {CGNAME}")
            except Exception as e:
                return False, f"Failed to create cgroup: {e}"

        procs_path = path / "cgroup.procs"
        if not procs_path.exists():
            return False, "cgroup.procs not found — is cgroups v2 mounted?"

        self.enabled = True
        logger.info(f"cgroup {CGNAME} ready")
        return True, "ok"

    def disable(self) -> tuple[bool, str]:
        if self.enabled:
            path = Path(self.cgroup_path)
            if path.exists():
                try:
                    path.rmdir()
                except Exception:
                    pass
            self.enabled = False
            logger.info(f"cgroup {CGNAME} removed")
        return True, "ok"

    def add_pid(self, pid: int) -> tuple[bool, str]:
        if not self.enabled:
            return True, "cgroup not enabled"
        procs_path = f"{self.cgroup_path}/cgroup.procs"
        try:
            with open(procs_path, "w") as f:
                f.write(str(pid))
            logger.debug(f"Added PID {pid} to cgroup {CGNAME}")
            return True, "ok"
        except Exception as e:
            return False, f"Failed to add PID {pid} to cgroup: {e}"

    def remove_pid(self, pid: int) -> tuple[bool, str]:
        if not self.enabled:
            return True, "cgroup not enabled"
        return True, "ok"

    def is_enabled(self) -> bool:
        return self.enabled


class NftablesManager:
    def __init__(self):
        self.fwmark = FW_MARK
        self.wg_fwmark = FW_MARK_WG
        self.table_name = "hanauta_split"
        self._current_vpn_iface: str | None = None
        self._current_config: SplitTunnelConfig | None = None

    def _apply_ruleset(self, ruleset: str) -> tuple[bool, str]:
        try:
            proc = subprocess.Popen(
                ["nft", "-f", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(input=ruleset, timeout=10)
            if proc.returncode != 0:
                return False, stderr or "nft apply failed"
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def teardown(self) -> tuple[bool, str]:
        ruleset = f"delete table inet {self.table_name}"
        ok, msg = self._apply_ruleset(ruleset)
        self._current_vpn_iface = None
        self._current_config = None
        return ok, msg

    def setup_base(self, vpn_iface: str, config: SplitTunnelConfig) -> tuple[bool, str]:
        self.teardown()
        self._current_vpn_iface = vpn_iface
        self._current_config = config

        fwmark_hex = f"0x{self.fwmark:x}"
        wg_fwmark_hex = f"0x{self.wg_fwmark:x}"

        ruleset = f"""
table inet {self.table_name} {{
    chain mangle {{
        type route hook output priority mangle; policy accept;
        socket cgroupv2 level 1 "{CGNAME}" counter meta mark set {fwmark_hex}
    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        oifname "{vpn_iface}" tcp flags syn tcp option maxseg size set 1200
        meta mark {fwmark_hex} oifname "{vpn_iface}" masquerade
    }}
}}
"""
        ok, msg = self._apply_ruleset(ruleset)
        if ok:
            logger.info(f"nftables app routing rules applied (table={self.table_name}, fwmark={fwmark_hex})")
        return ok, msg

    def setup_full_vpn(self, vpn_iface: str) -> tuple[bool, str]:
        self.teardown()
        self._current_vpn_iface = vpn_iface
        self._current_config = None

        fwmark_hex = f"0x{self.fwmark:x}"
        wg_fwmark_hex = f"0x{self.wg_fwmark:x}"

        ruleset = f"""
table inet {self.table_name} {{
    chain mangle {{
        type route hook output priority mangle; policy accept;
        meta mark != {wg_fwmark_hex} counter meta mark set {fwmark_hex}
    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        oifname "{vpn_iface}" tcp flags syn tcp option maxseg size set 1200
        oifname "{vpn_iface}" masquerade
    }}
}}
"""
        ok, msg = self._apply_ruleset(ruleset)
        if ok:
            logger.info(f"nftables full-VPN rules applied (table={self.table_name}, fwmark={fwmark_hex})")
        return ok, msg

    def enable_killswitch(self, vpn_iface: str, dns_ips: list[str]) -> tuple[bool, str]:
        self.teardown()
        self._current_vpn_iface = vpn_iface

        fwmark_hex = f"0x{self.fwmark:x}"

        dns_rules = ""
        for dns in dns_ips:
            dns_rules += f"        ip daddr {dns} udp dport 53 accept\n"
            dns_rules += f"        ip daddr {dns} tcp dport 53 accept\n"

        ruleset = f"""
table inet {self.table_name} {{
    chain mangle {{
        type route hook output priority mangle; policy accept;
        socket cgroupv2 level 1 "{CGNAME}" counter meta mark set {fwmark_hex}
    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        meta mark {fwmark_hex} oifname "{vpn_iface}" masquerade
    }}

    chain output {{
        type filter hook output priority filter; policy drop;
        oifname "{vpn_iface}" accept
        oifname "lo" accept
{dns_rules}        ct state established,related accept
        ip daddr 224.0.0.0/3 accept
        ip6 daddr ff00::/8 accept
        udp sport 68 udp dport 67 accept
        ip6 daddr fe80::/10 udp sport 546 udp dport 547 accept
        icmp type {{ router-solicitation, router-advertisement }} accept
        meta l4proto ipv6-icmp accept
    }}
}}
"""
        ok, msg = self._apply_ruleset(ruleset)
        if ok:
            logger.info("Kill switch enabled")
        return ok, msg


class RoutingManager:
    def __init__(self):
        self.fwmark = FW_MARK
        self.table = ROUTING_TABLE

    def add_host_route_vpn(self, ip: str, iface: str) -> tuple[bool, str]:
        logger.debug(f"Adding VPN host route: {ip} dev {iface}")
        if ":" in ip:
            return run_cmd(["ip", "-6", "route", "replace", ip, "dev", iface])
        return run_cmd(["ip", "-4", "route", "replace", ip, "dev", iface])

    def add_host_route_direct(self, ip: str) -> tuple[bool, str]:
        if ":" in ip:
            dev = self._get_default_interface_v6()
            if not dev:
                return False, "No IPv6 default interface"
            logger.debug(f"Adding direct host route: {ip} dev {dev}")
            return run_cmd(["ip", "-6", "route", "replace", ip, "dev", dev])
        gw = self._get_default_gateway()
        dev = self._get_default_interface()
        if not gw or not dev:
            return False, "No default gateway/interface"
        logger.debug(f"Adding direct host route: {ip} via {gw} dev {dev}")
        return run_cmd(["ip", "-4", "route", "replace", ip, "via", gw, "dev", dev])

    def del_host_route(self, ip: str) -> tuple[bool, str]:
        logger.debug(f"Deleting host route: {ip}")
        if ":" in ip:
            return run_cmd(["ip", "-6", "route", "del", ip])
        return run_cmd(["ip", "-4", "route", "del", ip])

    def add_fwmark_rule(self) -> tuple[bool, str]:
        fwmark_hex = f"0x{self.fwmark:x}"
        table = str(self.table)
        return run_cmd(["ip", "-4", "rule", "add", "fwmark", fwmark_hex, "table", table])

    def del_fwmark_rule(self) -> tuple[bool, str]:
        fwmark_hex = f"0x{self.fwmark:x}"
        table = str(self.table)
        return run_cmd(["ip", "-4", "rule", "del", "fwmark", fwmark_hex, "table", table])

    def _get_default_gateway(self) -> str | None:
        ok, out = run_cmd(["ip", "route", "show", "default"])
        if not ok:
            return None
        parts = out.split()
        try:
            via_idx = parts.index("via")
            return parts[via_idx + 1]
        except (ValueError, IndexError):
            return None

    def _get_default_interface(self) -> str | None:
        ok, out = run_cmd(["ip", "route", "show", "default"])
        if not ok:
            return None
        parts = out.split()
        try:
            dev_idx = parts.index("dev")
            return parts[dev_idx + 1]
        except (ValueError, IndexError):
            return None

    def _get_default_interface_v6(self) -> str | None:
        ok, out = run_cmd(["ip", "-6", "route", "show", "default"])
        if not ok:
            return None
        parts = out.split()
        try:
            dev_idx = parts.index("dev")
            return parts[dev_idx + 1]
        except (ValueError, IndexError):
            return None


class HostRoutesManager:
    def __init__(self, routing: RoutingManager):
        self.routing = routing
        self.vpn_iface: str | None = None
        self.current_routes: dict[str, str] = {}

    def set_vpn_interface(self, iface: str):
        self.vpn_iface = iface

    def clear_vpn_interface(self):
        self.vpn_iface = None

    def get_vpn_interface(self) -> str | None:
        return self.vpn_iface

    def update_routes(self, resolved: dict[str, list[str]]) -> tuple[bool, str]:
        new_routes = {}

        for key, ips in resolved.items():
            direction, domain = key.split(":", 1) if ":" in key else ("vpn", key)
            logger.debug(f"Updating routes for {direction}:{domain}: {ips}")

            for ip in ips:
                if ip in self.current_routes:
                    new_routes[ip] = key
                else:
                    route_ok = False
                    if direction == "vpn":
                        if self.vpn_iface:
                            route_ok, _ = self.routing.add_host_route_vpn(ip, self.vpn_iface)
                    elif direction == "direct":
                        route_ok, _ = self.routing.add_host_route_direct(ip)

                    if route_ok:
                        new_routes[ip] = key
                        logger.debug(f"Added host route: {ip} -> {direction}")
                    else:
                        logger.debug(f"Skipped host route {ip} -> {direction}")

        if self.vpn_iface:
            for ip in list(self.current_routes.keys()):
                if ip not in new_routes:
                    self.routing.del_host_route(ip)
                    logger.debug(f"Removed stale host route: {ip}")

        self.current_routes = new_routes
        logger.info(f"Host routes updated: {len(self.current_routes)} active routes")
        return True, "ok"

    def clear_all_routes(self) -> tuple[bool, str]:
        for ip in list(self.current_routes.keys()):
            self.routing.del_host_route(ip)
        self.current_routes.clear()
        return True, "ok"

    def route_count(self) -> int:
        return len(self.current_routes)


class DnsResolver:
    def __init__(self):
        pass

    async def resolve_domain(self, domain: str) -> list[str]:
        ips = []
        try:
            addrs = await asyncio.get_event_loop().getaddrinfo(domain, None, family=socket.AF_UNSPEC)
            for addr in addrs:
                ip = addr[4][0]
                if ip not in ips:
                    ips.append(ip)
        except Exception as e:
            logger.debug(f"DNS resolve failed for {domain}: {e}")
        return ips

    async def resolve_all(self, domains: list[str]) -> dict[str, list[str]]:
        results = {}
        tasks = [self.resolve_domain(d) for d in domains]
        resolved = await asyncio.gather(*tasks, return_exceptions=True)
        for domain, ips in zip(domains, resolved):
            if isinstance(ips, list) and ips:
                results[domain] = ips
            else:
                results[domain] = []
        return results


import socket


class ProcessMonitor:
    def __init__(self):
        self.app_paths: list[str] = []
        self.pid_to_app: dict[int, str] = {}
        self.flatpak_apps: dict[str, str] = {}

    def update_app_list(self, apps: list[str], flatpak_apps: dict[str, str] | None = None):
        self.app_paths = apps
        self.flatpak_apps = flatpak_apps or {}

    def _resolve_flatpak_path(self, app_id: str) -> str | None:
        try:
            result = subprocess.run(
                ["flatpak", "info", "-m", app_id],
                capture_output=True, text=True, timeout=5, check=False
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Location:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    def scan_all(self) -> list[int]:
        matched = []
        self.pid_to_app.clear()

        if not Path("/proc").exists():
            return matched

        try:
            entries = os.listdir("/proc")
        except Exception:
            return matched

        for entry in entries:
            if not entry.isdigit():
                continue
            pid = int(entry)
            app = self.check_process(pid)
            if app:
                logger.debug(f"Found matching process: PID={pid} app={app}")
                self.pid_to_app[pid] = app
                matched.append(pid)

        logger.info(f"Process scan found {len(matched)} matching processes")
        return matched

    def check_process(self, pid: int) -> str | None:
        exe_path = f"/proc/{pid}/exe"
        try:
            target = os.readlink(exe_path)
        except Exception:
            return None

        target_str = str(target)

        for app in self.app_paths:
            if target_str == app or target_str.endswith(app):
                return app

        if "flatpak-spawn" in target_str:
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
                for app_id in self.flatpak_apps:
                    if app_id in cmdline:
                        return self.flatpak_apps[app_id]
            except Exception:
                pass

        return None

    def is_watched(self, pid: int) -> bool:
        return pid in self.pid_to_app

    def add_pid(self, pid: int, app: str):
        self.pid_to_app[pid] = app

    def remove_pid(self, pid: int):
        self.pid_to_app.pop(pid, None)

    def watched_pids(self) -> list[int]:
        return list(self.pid_to_app.keys())


class SplitTunnelManager:
    def __init__(self):
        self.cgroup = CgroupManager()
        self.nftables = NftablesManager()
        self.routing = RoutingManager()
        self.host_routes = HostRoutesManager(self.routing)
        self.process_monitor = ProcessMonitor()
        self.dns_resolver = DnsResolver()

        self.config: SplitTunnelConfig | None = None
        self.vpn_iface: str | None = None

        self._dns_task: asyncio.Task | None = None
        self._process_task: asyncio.Task | None = None
        self._cancel_dns = threading.Event()
        self._cancel_process = threading.Event()
        self._lock = threading.Lock()

    def apply_config(self, config: SplitTunnelConfig, vpn_iface: str | None) -> tuple[bool, str]:
        with self._lock:
            if not config.enabled:
                return self.disable()

            self.config = config
            self.vpn_iface = vpn_iface

            ok, msg = self.cgroup.enable()
            if not ok:
                return ok, msg

            app_list = config.get_app_list()
            flatpak_apps = self._get_flatpak_apps()
            self.process_monitor.update_app_list(app_list, flatpak_apps)

            matched = self.process_monitor.scan_all()
            if matched:
                logger.warning(
                    f"Adding {len(matched)} already-running process(es) to cgroup. "
                    f"Existing network connections will NOT be rerouted — "
                    f"only new connections will use the VPN."
                )
                for pid in matched:
                    self.cgroup.add_pid(pid)

            self._start_process_monitor()

            if vpn_iface:
                ok, msg = self.nftables.setup_base(vpn_iface, config)
                if not ok:
                    logger.warning(f"Failed to setup nftables for app routing: {msg}")

            if config.kill_switch and vpn_iface:
                dns_ips = self._get_dns_ips(vpn_iface)
                ok, msg = self.nftables.enable_killswitch(vpn_iface, dns_ips)
                if not ok:
                    logger.warning(f"Failed to enable kill switch: {msg}")

            if config.domains_vpn or config.domains_direct:
                self._start_dns_loop()

            logger.info(f"Split tunneling enabled (mode={config.mode}, iface={vpn_iface})")
            return True, "Split tunneling enabled"

    def on_tunnel_connected(self, iface: str) -> tuple[bool, str]:
        with self._lock:
            self.vpn_iface = iface
            self.host_routes.set_vpn_interface(iface)

            if self.config and self.config.enabled:
                ok, msg = self.apply_config(self.config, iface)
                if not ok:
                    logger.warning(f"Failed to re-apply split tunneling on connect: {msg}")
                return ok, msg
            else:
                ok, msg = self.nftables.setup_full_vpn(iface)
                if not ok:
                    logger.warning(f"Failed to setup full-VPN nftables after tunnel connect: {msg}")
                return ok, msg

    def on_tunnel_disconnected(self) -> tuple[bool, str]:
        with self._lock:
            self._stop_dns_loop()
            self._stop_process_monitor()

            self.nftables.teardown()

            self.cgroup.disable()

            self.host_routes.clear_vpn_interface()
            self.host_routes.clear_all_routes()

            self.vpn_iface = None
            logger.info("Split tunneling stopped (tunnel disconnected)")
            return True, "Split tunneling stopped"

    def disable(self) -> tuple[bool, str]:
        with self._lock:
            self._stop_dns_loop()
            self._stop_process_monitor()

            self.cgroup.disable()

            self.host_routes.clear_all_routes()

            vpn_iface = self.host_routes.get_vpn_interface()
            if vpn_iface:
                self.nftables.setup_full_vpn(vpn_iface)
            else:
                self.nftables.teardown()

            if self.config:
                self.config.enabled = False

            self.vpn_iface = None
            logger.info("Split tunneling disabled")
            return True, "Split tunneling disabled"

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.enabled if self.config else False,
                "mode": self.config.mode if self.config else "inclusive",
                "kill_switch": self.config.kill_switch if self.config else False,
                "vpn_interface": self.vpn_iface,
                "tracked_pids": len(self.process_monitor.watched_pids()),
                "active_routes": self.host_routes.route_count(),
                "cgroup_enabled": self.cgroup.is_enabled(),
                "apps_vpn": self.config.apps_vpn if self.config else [],
                "apps_direct": self.config.apps_direct if self.config else [],
                "domains_vpn": self.config.domains_vpn if self.config else [],
                "domains_direct": self.config.domains_direct if self.config else [],
            }

    def _get_flatpak_apps(self) -> dict[str, str]:
        apps = {}
        try:
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application,name"],
                capture_output=True, text=True, timeout=5, check=False
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = [p.strip() for p in line.split("\t") if p.strip()]
                    if len(parts) >= 2:
                        apps[parts[0]] = parts[1]
        except Exception:
            pass
        return apps

    def _get_dns_ips(self, iface: str) -> list[str]:
        ips = []
        try:
            result = subprocess.run(
                ["resolvectl", "dns", iface],
                capture_output=True, text=True, timeout=5, check=False
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    for part in line.split():
                        if "." in part and part.replace(".", "").isdigit():
                            ips.append(part)
        except Exception:
            pass
        return ips

    def _start_process_monitor(self):
        self._cancel_process.clear()
        self._process_task = asyncio.create_task(self._process_monitor_loop())

    def _stop_process_monitor(self):
        self._cancel_process.set()
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None

    async def _process_monitor_loop(self):
        while not self._cancel_process.is_set():
            await asyncio.sleep(2)
            if self._cancel_process.is_set():
                break

            try:
                entries = os.listdir("/proc")
            except Exception:
                continue

            for entry in entries:
                if not entry.isdigit():
                    continue
                pid = int(entry)
                is_watched = self.process_monitor.is_watched(pid)
                if not is_watched:
                    app = self.process_monitor.check_process(pid)
                    if app:
                        logger.debug(f"New matching process: PID={pid} app={app}")
                        self.process_monitor.add_pid(pid, app)
                        self.cgroup.add_pid(pid)

    def _start_dns_loop(self):
        self._cancel_dns.clear()
        self._dns_task = asyncio.create_task(self._dns_loop())

    def _stop_dns_loop(self):
        self._cancel_dns.set()
        if self._dns_task:
            self._dns_task.cancel()
            self._dns_task = None

    async def _dns_loop(self):
        while not self._cancel_dns.is_set():
            if not self.config or not self.vpn_iface:
                break

            config = self.config
            vpn_domains = config.domains_vpn
            direct_domains = config.domains_direct

            if not vpn_domains and not direct_domains:
                break

            try:
                all_resolved = {}
                all_ok = True

                vpn_results = await self.dns_resolver.resolve_all(vpn_domains)
                if self._cancel_dns.is_set():
                    break
                for domain, ips in vpn_results.items():
                    if not ips:
                        all_ok = False
                    else:
                        all_resolved[f"vpn:{domain}"] = ips

                direct_results = await self.dns_resolver.resolve_all(direct_domains)
                if self._cancel_dns.is_set():
                    break
                for domain, ips in direct_results.items():
                    if not ips:
                        all_ok = False
                    else:
                        all_resolved[f"direct:{domain}"] = ips

                if all_ok and all_resolved:
                    self.host_routes.update_routes(all_resolved)

            except Exception as e:
                logger.warning(f"DNS loop error: {e}")

            try:
                await asyncio.sleep(config.resolve_interval_secs)
            except asyncio.CancelledError:
                break


_split_tunnel_manager: SplitTunnelManager | None = None


def get_split_tunnel_manager() -> SplitTunnelManager:
    global _split_tunnel_manager
    if _split_tunnel_manager is None:
        _split_tunnel_manager = SplitTunnelManager()
    return _split_tunnel_manager


def handle_split_tunnel_request(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    mgr = get_split_tunnel_manager()

    if action == "enable_split_tunnel":
        config = SplitTunnelConfig.from_dict(payload.get("config", {}))
        vpn_iface = payload.get("interface")
        ok, msg = mgr.apply_config(config, vpn_iface)
        return {"ok": ok, "message": msg, "status": mgr.get_status()}

    elif action == "disable_split_tunnel":
        ok, msg = mgr.disable()
        return {"ok": ok, "message": msg, "status": mgr.get_status()}

    elif action == "on_tunnel_connected":
        iface = payload.get("interface", "")
        ok, msg = mgr.on_tunnel_connected(iface)
        return {"ok": ok, "message": msg, "status": mgr.get_status()}

    elif action == "on_tunnel_disconnected":
        ok, msg = mgr.on_tunnel_disconnected()
        return {"ok": ok, "message": msg, "status": mgr.get_status()}

    elif action == "set_split_config":
        config = SplitTunnelConfig.from_dict(payload.get("config", {}))
        vpn_iface = mgr.vpn_iface
        ok, msg = mgr.apply_config(config, vpn_iface)
        return {"ok": ok, "message": msg, "status": mgr.get_status()}

    elif action == "get_split_status":
        return {"ok": True, "status": mgr.get_status()}

    return {"ok": False, "message": f"Unknown split tunnel action: {action}"}