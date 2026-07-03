#!/usr/bin/env python3
"""
DNS-VPN Gateway
Шлюз-прокси + DNS-сервер с веб-интерфейсом.
Перехватывает DNS-запросы для указанных доменов,
резолвит их IP и направляет трафик через VPN (wg0) 
используя ipset + policy routing.
"""

import threading
import sys
import signal
import subprocess

from config import DNS_PORT, WEB_PORT, WEB_HOST, VPN_INTERFACE
from domain_store import DomainStore
from route_manager import RouteManager
from dns_server import DNSServer
from wg_manager import WireGuardManager
from web_ui import app as web_app
import web_ui

# Глобальные переменные для graceful shutdown
running = True


def signal_handler(signum, frame):
    global running
    print("\n[MAIN] Получен сигнал завершения...")
    running = False
    sys.exit(0)


def setup_nft_rules(vpn_iface):
    """Настроить nftables: MASQUERADE + FORWARD для VPN"""
    # NAT masquerade для трафика через wg0
    subprocess.run(
        ["nft", "add", "table", "ip", "nat"],
        capture_output=True, timeout=5
    )
    subprocess.run(
        ["nft", "add", "chain", "ip", "nat", "postrouting",
         "{ type nat hook postrouting priority srcnat ; policy accept ; }"],
        capture_output=True, timeout=5
    )
    subprocess.run(
        ["nft", "add", "rule", "ip", "nat", "postrouting",
         "oifname", vpn_iface, "masquerade"],
        capture_output=True, timeout=5
    )
    # FORWARD правила
    subprocess.run(
        ["nft", "add", "table", "ip", "filter"],
        capture_output=True, timeout=5
    )
    subprocess.run(
        ["nft", "add", "chain", "ip", "filter", "forward",
         "{ type filter hook forward priority filter ; policy accept ; }"],
        capture_output=True, timeout=5
    )
    subprocess.run(
        ["nft", "add", "rule", "ip", "filter", "forward",
         "iifname", vpn_iface, "accept"],
        capture_output=True, timeout=5
    )
    subprocess.run(
        ["nft", "add", "rule", "ip", "filter", "forward",
         "oifname", vpn_iface, "accept"],
        capture_output=True, timeout=5
    )
    print(f"[MAIN] NAT и FORWARD для {vpn_iface} настроены")


def cleanup_old_routes(vpn_iface):
    """Очистить старые точечные маршруты через wg0 (от предыдущей версии)"""
    result = subprocess.run(
        ["ip", "route", "show", "dev", vpn_iface],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] != "default":
                ip = parts[0]
                subprocess.run(
                    ["ip", "route", "del", ip, "dev", vpn_iface],
                    capture_output=True, timeout=5
                )
                print(f"[MAIN] Удалён старый точечный маршрут: {ip}")


def main():
    print("=" * 50)
    print("   DNS-VPN Gateway")
    print("   Шлюз + DNS + VPN маршрутизация через WireGuard")
    print("=" * 50)

    # Инициализация компонентов
    store = DomainStore()
    rm = RouteManager()
    wg = WireGuardManager(interface=VPN_INTERFACE)

    # Подключаем их к веб-интерфейсу
    web_ui.domain_store = store
    web_ui.route_manager = rm
    web_ui.wg_manager = wg

    # DNS-сервер
    dns = DNSServer(store, rm)

    # Регистрируем обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"[MAIN] DNS-сервер на :{DNS_PORT}")
    print(f"[MAIN] Веб-интерфейс на http://{WEB_HOST}:{WEB_PORT}")
    print(f"[MAIN] VPN интерфейс: {VPN_INTERFACE}")

    # Очистка старых точечных маршрутов
    cleanup_old_routes(VPN_INTERFACE)

    # Настройка policy routing
    rm.setup_policy_routing()

    # Информация о WireGuard
    wg_up = False
    if wg.has_config():
        print(f"[MAIN] Конфиг WireGuard найден: {wg.config_path}")
        wg_status = wg.get_status()
        if wg_status["up"]:
            wg_up = True
            print(f"[MAIN] WireGuard {VPN_INTERFACE} активен")
        else:
            print(f"[MAIN] WireGuard {VPN_INTERFACE} не запущен")
    else:
        print(f"[MAIN] Конфиг WireGuard не найден ({wg.config_path})")
        print(f"[MAIN] Загрузите конфиг через веб-интерфейс")

    # NAT + FORWARD если WG активен
    if wg_up:
        setup_nft_rules(VPN_INTERFACE)

    # Синхронизируем сохранённые IP при старте
    managed_ips = set()
    for domain in store.list_domains():
        for ip in store.get_domain_ips(domain):
            managed_ips.add(ip)
    if managed_ips:
        print(f"[MAIN] Синхронизация {len(managed_ips)} IP в ipset...")
        rm.sync_routes(managed_ips)

    # Запускаем DNS-сервер в отдельном потоке
    dns_thread = threading.Thread(target=dns.start, daemon=True)
    dns_thread.start()

    # Запускаем веб-интерфейс (блокирует основной поток)
    web_app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()