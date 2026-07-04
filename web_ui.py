import threading
from flask import Flask, render_template, request, jsonify
from config import WEB_HOST, WEB_PORT, VPN_INTERFACE, DNS_PORT, DATA_FILE
from domain_store import DomainStore
from route_manager import RouteManager
from wg_manager import WireGuardManager
import subprocess
import json
import os
import time

app = Flask(__name__)

# Эти будут установлены из main
domain_store: DomainStore = None
route_manager: RouteManager = None
wg_manager: WireGuardManager = None


@app.route("/")
def index():
    domains = domain_store.list_domains()
    domain_ips = {}
    for d in domains:
        ips = domain_store.get_domain_ips(d)
        domain_ips[d] = ips
    routes = route_manager.get_active_routes()
    wg_config = wg_manager.get_config() if wg_manager else ""
    wg_status = wg_manager.get_status() if wg_manager else {"up": False, "has_config": False}
    return render_template(
        "index.html",
        domains=domains,
        domain_ips=domain_ips,
        routes=routes,
        wg_config=wg_config,
        wg_status=wg_status,
        dns_port=DNS_PORT,
        web_port=WEB_PORT
    )


# ===== API: Domain Management =====

@app.route("/api/domains", methods=["GET"])
def api_list_domains():
    domains = domain_store.list_domains()
    result = {}
    for d in domains:
        ips = domain_store.get_domain_ips(d)
        result[d] = ips
    return jsonify(result)


@app.route("/api/domains/detail", methods=["GET"])
def api_list_domains_detail():
    """Вернуть домены с мета-данными IP (ttl, last_resolved)"""
    domains = domain_store.list_domains()
    result = {}
    now = time.time()
    for d in domains:
        ips_meta = domain_store.get_domain_ips_with_meta(d)
        result[d] = {}
        for ip, meta in ips_meta.items():
            last_resolved = meta.get("last_resolved", 0)
            ttl = meta.get("ttl", 300)
            # человекочитаемое время
            if last_resolved > 0:
                age = int(now - last_resolved)
                result[d][ip] = {
                    "ttl": ttl,
                    "age_sec": age,
                    "last_resolved_ago": f"{age // 60}m {age % 60}s ago" if age < 3600 else f"{age // 3600}h {(age % 3600) // 60}m ago"
                }
            else:
                result[d][ip] = {"ttl": ttl, "age_sec": 0, "last_resolved_ago": "not resolved"}
    return jsonify(result)


@app.route("/api/domains/add", methods=["POST"])
def api_add_domain():
    data = request.get_json()
    if not data or "domain" not in data:
        return jsonify({"error": "Поле 'domain' обязательно"}), 400
    domain = data["domain"].strip().lower()
    if not domain:
        return jsonify({"error": "Домен не может быть пустым"}), 400
    if domain_store.add_domain(domain):
        return jsonify({"status": "ok", "domain": domain})
    return jsonify({"error": "Домен уже существует", "domain": domain}), 409


@app.route("/api/domains/remove", methods=["POST"])
def api_remove_domain():
    data = request.get_json()
    if not data or "domain" not in data:
        return jsonify({"error": "Поле 'domain' обязательно"}), 400
    domain = data["domain"].strip().lower()
    removed_ips = domain_store.remove_domain(domain)
    for ip in removed_ips:
        route_manager.remove_route(ip)
    return jsonify({"status": "ok", "domain": domain, "removed_ips": list(removed_ips.keys())})


@app.route("/api/domains/export", methods=["GET"])
def api_export_domains():
    domains = domain_store.list_domains()
    result = {}
    for d in sorted(domains):
        ips = domain_store.get_domain_ips(d)
        result[d] = ips
    return jsonify(result)


@app.route("/api/domains/import", methods=["POST"])
def api_import_domains():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Ожидается объект с доменами"}), 400
    
    added = []
    for domain in data:
        domain = domain.strip().lower()
        if domain and domain_store.add_domain(domain):
            added.append(domain)
    
    return jsonify({"status": "ok", "added": len(added)})


# ===== API: Routes =====

@app.route("/api/routes", methods=["GET"])
def api_list_routes():
    routes = route_manager.get_active_routes()
    return jsonify({"routes": routes})


# ===== API: WireGuard =====

@app.route("/api/wg/status", methods=["GET"])
def api_wg_status():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    status = wg_manager.get_status()
    return jsonify(status)


@app.route("/api/wg/config", methods=["GET"])
def api_wg_get_config():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    return jsonify({
        "config": wg_manager.get_config(),
        "has_config": wg_manager.has_config()
    })


@app.route("/api/wg/config", methods=["POST"])
def api_wg_save_config():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    data = request.get_json()
    if not data or "config" not in data:
        return jsonify({"error": "Поле 'config' обязательно"}), 400
    success, error = wg_manager.save_config(data["config"])
    if success:
        return jsonify({"status": "ok", "message": "Конфиг сохранён"})
    return jsonify({"error": error}), 400


@app.route("/api/wg/start", methods=["POST"])
def api_wg_start():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    success, message = wg_manager.start()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 500


@app.route("/api/wg/stop", methods=["POST"])
def api_wg_stop():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    success, message = wg_manager.stop()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 500


@app.route("/api/wg/restart", methods=["POST"])
def api_wg_restart():
    if not wg_manager:
        return jsonify({"error": "WG Manager не инициализирован"}), 500
    success, message = wg_manager.restart()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 500


# ===== API: Status =====

@app.route("/api/status", methods=["GET"])
def api_status():
    wg_status = wg_manager.get_status() if wg_manager else {}
    return jsonify({
        "domains_count": len(domain_store.list_domains()),
        "routes_count": len(route_manager.get_active_routes()),
        "vpn_interface": VPN_INTERFACE,
        "wg_up": wg_status.get("up", False),
        "wg_has_config": wg_status.get("has_config", False),
        "wg_default_via_wg": wg_status.get("default_via_wg", False)
    })


# ===== API: Settings =====

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.py")

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({
        "dns_port": DNS_PORT,
        "web_port": WEB_PORT,
        "vpn_interface": VPN_INTERFACE
    })


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    """Сохранить настройки портов в config.py"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Нет данных"}), 400
    
    new_dns = data.get("dns_port", DNS_PORT)
    new_web = data.get("web_port", WEB_PORT)
    
    try:
        with open(CONFIG_FILE, "r") as f:
            content = f.read()
    except:
        return jsonify({"error": "Не удалось прочитать config.py"}), 500
    
    import re
    content = re.sub(r'WEB_PORT\s*=\s*int\(os\.getenv\("WEB_PORT",\s*"[^"]*"\)\)',
                     f'WEB_PORT = int(os.getenv("WEB_PORT", "{new_web}"))', content)
    content = re.sub(r'DNS_PORT\s*=\s*int\(os\.getenv\("DNS_PORT",\s*"[^"]*"\)\)',
                     f'DNS_PORT = int(os.getenv("DNS_PORT", "{new_dns}"))', content)
    
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(content)
    except:
        return jsonify({"error": "Не удалось записать config.py"}), 500
    
    return jsonify({"status": "ok", "message": "Настройки сохранены. Перезапустите сервис для применения."})


# ===== API: Backup =====

@app.route("/api/backup/export", methods=["GET"])
def api_backup_export():
    """Полный экспорт: WG конфиг + домены + их IP"""
    wg_config = wg_manager.get_config() if wg_manager else ""
    
    domains = {}
    for d in sorted(domain_store.list_domains()):
        ips = domain_store.get_domain_ips(d)
        domains[d] = ips
    
    backup = {
        "version": "1.0",
        "dns_port": DNS_PORT,
        "web_port": WEB_PORT,
        "vpn_interface": VPN_INTERFACE,
        "wireguard_config": wg_config,
        "domains": domains,
        "active_routes": route_manager.get_active_routes(),
        "exported_at": __import__('datetime').datetime.now().isoformat()
    }
    
    return jsonify(backup)


@app.route("/api/backup/import", methods=["POST"])
def api_backup_import():
    """Полный импорт: WG конфиг + домены"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Нет данных"}), 400
    
    results = {"domains_added": 0, "wg_config_loaded": False}
    
    if "wireguard_config" in data and data["wireguard_config"]:
        if wg_manager:
            success, error = wg_manager.save_config(data["wireguard_config"])
            if success:
                results["wg_config_loaded"] = True
    
    if "domains" in data and isinstance(data["domains"], dict):
        for domain in data["domains"]:
            domain = domain.strip().lower()
            if domain and domain_store.add_domain(domain):
                results["domains_added"] += 1
    
    return jsonify({
        "status": "ok",
        "message": f"Импортировано: {results['domains_added']} доменов, WG конфиг {'загружен' if results['wg_config_loaded'] else 'не изменён'}",
        "details": results
    })


# ===== API: Presets =====

PRESETS = {
    "youtube": {
        "name": "YouTube",
        "domains": [
            "*.youtube.com", "*.ytimg.com", "*.googlevideo.com",
            "*.googleapis.com", "*.ggpht.com", "*.youtu.be",
            "*.yt.be", "*.withyoutube.com"
        ]
    },
    "telegram": {
        "name": "Telegram",
        "domains": [
            "*.telegram.org", "*.t.me", "*.telegram.me",
            "*.stel.com", "*.tg.dev"
        ]
    },
    "chatgpt": {
        "name": "ChatGPT",
        "domains": [
            "*.openai.com", "*.chatgpt.com", "*.oaistatic.com",
            "*.oaiusercontent.com", "*.ai.com", "*.chat.com"
        ]
    }
}

@app.route("/api/presets", methods=["GET"])
def api_presets():
    return jsonify({k: v["name"] for k, v in PRESETS.items()})


@app.route("/api/presets/<preset_id>/apply", methods=["POST"])
def api_apply_preset(preset_id):
    if preset_id not in PRESETS:
        return jsonify({"error": "Пресет не найден"}), 404
    
    preset = PRESETS[preset_id]
    added = []
    for domain in preset["domains"]:
        if domain_store.add_domain(domain):
            added.append(domain)
    
    return jsonify({"status": "ok", "preset": preset_id, "name": preset["name"], "added": len(added)})


@app.route("/api/presets/<preset_id>/remove", methods=["POST"])
def api_remove_preset(preset_id):
    if preset_id not in PRESETS:
        return jsonify({"error": "Пресет не найден"}), 404
    
    preset = PRESETS[preset_id]
    removed = []
    for domain in preset["domains"]:
        removed_ips = domain_store.remove_domain(domain)
        for ip in removed_ips:
            route_manager.remove_route(ip)
        if removed_ips is not None:
            removed.append(domain)
    
    return jsonify({"status": "ok", "preset": preset_id, "name": preset["name"], "removed": len(removed)})


def run_web_server():
    print(f"[WEB] Веб-интерфейс запущен на http://{WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)