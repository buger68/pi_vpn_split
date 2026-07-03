import subprocess
import threading
from config import VPN_INTERFACE

VPN_TABLE = "100"
VPN_MARK = "0x01"


class RouteManager:
    """Управление маршрутизацией — точечные маршруты + policy routing"""

    def __init__(self):
        self._lock = threading.Lock()
        self.active_ips = set()

    def _run_cmd(self, cmd: list, check=True) -> bool:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                if check:
                    print(f"[ROUTE] Ошибка: {' '.join(cmd)} -> {result.stderr.strip()}")
                return False
            return True
        except Exception as e:
            print(f"[ROUTE] Исключение: {e}")
            return False

    def add_route(self, ip: str) -> bool:
        """Добавить точечный маршрут через wg0"""
        with self._lock:
            if ip in self.active_ips:
                return True
            success = self._run_cmd([
                "/usr/sbin/ip", "route", "add", ip,
                "dev", VPN_INTERFACE
            ])
            if success:
                self.active_ips.add(ip)
            return success

    def remove_route(self, ip: str) -> bool:
        """Удалить точечный маршрут"""
        with self._lock:
            if ip not in self.active_ips:
                return True
            success = self._run_cmd([
                "/usr/sbin/ip", "route", "del", ip,
                "dev", VPN_INTERFACE
            ], check=False)
            if success:
                self.active_ips.discard(ip)
            return success

    def sync_routes(self, ips: set):
        """Синхронизировать маршруты: добавить новые, удалить лишние"""
        with self._lock:
            to_add = ips - self.active_ips
            for ip in to_add:
                if self._run_cmd(["/usr/sbin/ip", "route", "add", ip, "dev", VPN_INTERFACE]):
                    self.active_ips.add(ip)
            to_remove = self.active_ips - ips
            for ip in to_remove:
                if self._run_cmd(["/usr/sbin/ip", "route", "del", ip, "dev", VPN_INTERFACE], check=False):
                    self.active_ips.discard(ip)
            print(f"[ROUTE] Синхронизация: {len(self.active_ips)} маршрутов")

    def get_active_routes(self) -> list:
        with self._lock:
            return sorted(list(self.active_ips))

    def get_current_routes_from_system(self) -> set:
        """Получить текущие точечные маршруты через wg0 из системы"""
        try:
            result = subprocess.run(
                ["/usr/sbin/ip", "route", "show", "dev", VPN_INTERFACE],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return set()
            routes = set()
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts and parts[0] != "default":
                    routes.add(parts[0])
            return routes
        except Exception as e:
            print(f"[ROUTE] Ошибка получения маршрутов: {e}")
            return set()

    def setup_policy_routing(self, priority='4000'):
        """Настроить policy routing — защита от wg-quick"""
        print(f"[ROUTE] Настройка policy routing (приоритет {priority})...")

        # iptables mangle
        self._run_cmd([
            "/usr/sbin/iptables", "-t", "mangle", "-C", "PREROUTING",
            "-m", "set", "--match-set", "vpn_domains", "dst",
            "-j", "MARK", "--set-mark", VPN_MARK
        ], check=False)
        self._run_cmd([
            "/usr/sbin/iptables", "-t", "mangle", "-A", "PREROUTING",
            "-m", "set", "--match-set", "vpn_domains", "dst",
            "-j", "MARK", "--set-mark", VPN_MARK
        ], check=False)
        self._run_cmd([
            "/usr/sbin/iptables", "-t", "mangle", "-C", "FORWARD",
            "-m", "set", "--match-set", "vpn_domains", "dst",
            "-j", "MARK", "--set-mark", VPN_MARK
        ], check=False)
        self._run_cmd([
            "/usr/sbin/iptables", "-t", "mangle", "-A", "FORWARD",
            "-m", "set", "--match-set", "vpn_domains", "dst",
            "-j", "MARK", "--set-mark", VPN_MARK
        ], check=False)

        # Таблица 100
        self._run_cmd([
            "/usr/sbin/ip", "route", "replace", "default", "dev", VPN_INTERFACE, "table", VPN_TABLE
        ])

        # Наше правило
        self._run_cmd(["/usr/sbin/ip", "rule", "del", "fwmark", VPN_MARK, "table", VPN_TABLE], check=False)
        self._run_cmd(["/usr/sbin/ip", "rule", "del", "priority", priority], check=False)
        self._run_cmd([
            "/usr/sbin/ip", "rule", "add", "fwmark", VPN_MARK, "table", VPN_TABLE,
            "priority", priority
        ])

        print(f"[ROUTE] Policy routing настроен: mark={VPN_MARK}, table={VPN_TABLE}, priority={priority}")

    def cleanup_policy_routing(self):
        self._run_cmd(["/usr/sbin/ip", "rule", "del", "fwmark", VPN_MARK, "table", VPN_TABLE], check=False)
        self._run_cmd(["/usr/sbin/ip", "route", "flush", "table", VPN_TABLE], check=False)
        for chain in ["PREROUTING", "FORWARD"]:
            self._run_cmd([
                "/usr/sbin/iptables", "-t", "mangle", "-D", chain,
                "-m", "set", "--match-set", "vpn_domains", "dst",
                "-j", "MARK", "--set-mark", VPN_MARK
            ], check=False)
        print("[ROUTE] Policy routing очищен")