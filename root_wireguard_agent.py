#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

CONF_FILE = Path('/etc/hanauta-wireguard-autoconnect.conf')
RUN_DIR = Path('/run/hanauta-wireguard-agent')
REQUEST_FILE = RUN_DIR / 'request.json'
RESPONSE_FILE = RUN_DIR / 'response.json'


def load_conf() -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        raw = CONF_FILE.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return data
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        data[k.strip()] = v.strip()
    return data


def home_dir() -> Path:
    conf = load_conf()
    home = conf.get('HANAUTA_USER_HOME', '').strip()
    if home:
        return Path(home)
    return Path('/home/gabi')


def cache_file() -> Path:
    return home_dir() / '.local' / 'state' / 'hanauta' / 'service' / 'plugins' / 'vpn_control_wireguard.json'


def list_ifaces() -> list[str]:
    wg_dir = Path('/etc/wireguard')
    if not wg_dir.exists() or not wg_dir.is_dir():
        return []
    return sorted([p.stem for p in wg_dir.glob('*.conf') if p.stem])


def link_up(iface: str) -> bool:
    if not iface:
        return False
    result = subprocess.run(['ip', 'link', 'show', iface], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False
    text = result.stdout
    if " state UP " in text:
        return True
    if "<" in text and ">" in text:
        try:
            flags = text.split("<", 1)[1].split(">", 1)[0]
            parts = [part.strip().upper() for part in flags.split(",") if part.strip()]
            if "UP" in parts:
                return True
        except Exception:
            pass
    return False


def run_cmd(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60.0, check=False)
    except Exception as exc:
        return False, str(exc)
    ok = result.returncode == 0
    out = (result.stdout or '').strip()
    err = (result.stderr or '').strip()
    return ok, (out or err or ('ok' if ok else 'failed'))


def write_cache(selected: str | None = None) -> dict[str, object]:
    ifaces = list_ifaces()
    conf = load_conf()
    preferred = conf.get('WG_IFACE', '').strip()
    chosen = (selected or '').strip() or preferred
    if chosen not in ifaces:
        chosen = ifaces[0] if ifaces else ''
    payload = {
        'wireguard': 'on' if link_up(chosen) else 'off',
        'wg_selected': chosen,
        'interfaces': ifaces,
    }
    path = cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')
    return payload


def handle_request(req: dict[str, object]) -> dict[str, object]:
    request_id = str(req.get('request_id', '')).strip()
    action = str(req.get('action', '')).strip().lower()
    iface = str(req.get('interface', '')).strip()
    if action == 'list_interfaces':
        payload = write_cache(selected=iface)
        return {'ok': True, 'message': 'interfaces refreshed', 'payload': payload, 'request_id': request_id}
    if action == 'toggle':
        if not iface:
            payload = write_cache()
            iface = str(payload.get('wg_selected', '')).strip()
        if not iface:
            return {'ok': False, 'message': 'No WireGuard interface selected.', 'request_id': request_id}
        if link_up(iface):
            ok, msg = run_cmd(['wg-quick', 'down', iface])
        else:
            ok, msg = run_cmd(['wg-quick', 'up', iface])
        payload = write_cache(selected=iface)
        return {'ok': ok, 'message': msg, 'payload': payload, 'request_id': request_id}
    return {'ok': False, 'message': f'Unknown action: {action}', 'request_id': request_id}


def ensure_runtime() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, 0o777)
    for p in (REQUEST_FILE, RESPONSE_FILE):
        if not p.exists():
            p.write_text('{}', encoding='utf-8')
        os.chmod(p, 0o666)


def main() -> int:
    ensure_runtime()
    write_cache()
    last_mtime = 0.0
    while True:
        try:
            stat = REQUEST_FILE.stat()
            if stat.st_mtime > last_mtime:
                last_mtime = stat.st_mtime
                req = json.loads(REQUEST_FILE.read_text(encoding='utf-8'))
                res = handle_request(req if isinstance(req, dict) else {})
                res['ts'] = time.time()
                RESPONSE_FILE.write_text(json.dumps(res, ensure_ascii=True), encoding='utf-8')
                os.chmod(RESPONSE_FILE, 0o666)
            write_cache()
        except Exception:
            pass
        time.sleep(1.0)


if __name__ == '__main__':
    raise SystemExit(main())
