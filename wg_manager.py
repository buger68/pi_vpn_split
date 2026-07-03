import os
import subprocess
import re
import shutil

WG_CONFIG_DIR = "/etc/wireguard"
WG_INTERFACE = None


class WireGuardManager:
    """Управление WireGuard: конфиг, старт/стоп, статус"""

    def __init__(self, interface="wg0"):
        self.interface = interface
        self.config_path = os.path.join(WG_CONFIG_DIR, f"{interface}.conf")

    def _run(self, cmd: list, timeout=15) -> tuple:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "Timeout", -1
        except FileNotFoundError:
            return "", "Command not found", -2

    def has_config(self) -> bool:
        return os.path.exists(self.config_path)

    def get_config(self) -> str:
        if self.has_config():
            try:
                with open(self.config_path, "r") as f:
                    return f.read()
            except IOError as e:
                return f"# Ошибка чтения: {e}"
        return "# Конфиг не найден"

    def save_config(self, content: str) -> tuple:
        os.makedirs(WG_CONFIG_DIR, exist_ok=True)
        if "[Interface]" not in content:
            return False, "Конфиг должен содержать секцию [Interface]"
        if "PrivateKey" not in content:
            return False, "В секции [Interface] должен быть PrivateKey"
        try:
            with open(self.config_path, "w") as f:
                f.write(content)
            os.chmod(self.config_path, 0o600)
            return True, None
        except IOError as e:
            return False, f"Ошибка записи: {e}"

    def get_status(self) -> dict:
        stdout, stderr, rc = self._run(["ip", "link", "show", self.interface])
        if rc != 0:
            return {"up": False, "has_config": self.has_config(), "error": "Интерфейс не найден", "detail": {}}
        is_up = "state UP" in stdout or "state UNKNOWN" in stdout
        detail = {}
        wg_out, wg_err, wg_rc = self._run(["wg", "show", self.interface])
        if wg_rc == 0:
            for line in wg_out.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    detail[key.strip()] = val.strip()
                elif "peer" in line.lower():
                    peer = line.split()[-1] if line.split() else ""
                    detail.setdefault("peers", []).append({"public_key": peer})
        route_out, _, _ = self._run(["ip", "route", "show", "dev", self.interface])
        routes = []
        default_via_wg = False
        for line in route_out.splitlines():
            routes.append(line)
            if line.startswith("default"):
                default_via_wg = True
        return {
            "up": is_up,
            "has_config": self.has_config(),
            "interface": self.interface,
            "detail": detail,
            "routes": routes,
            "default_via_wg": default_via_wg,
            "routes_count": len(routes)
        }

    def start(self) -> tuple:
        """Запустить WireGuard интерфейс. Возвращает (success, message)"""
        if not self.has_config():
            return False, "Нет конфигурации WireGuard"
        status = self.get_status()
        if status["up"]:
            return True, f"{self.interface} уже запущен"
        stdout, stderr, rc = self._run(["wg-quick", "up", self.interface])
        if rc == 0:
            return True, f"{self.interface} запущен"
        stdout2, stderr2, rc2 = self._run(["wg", "setconf", self.interface, self.config_path])
        if rc2 != 0:
            return False, f"Ошибка запуска: {stderr or stderr2}"
        self._run(["ip", "link", "set", self.interface, "up"])
        return True, f"{self.interface} запущен (метод wg setconf)"

    def stop(self) -> tuple:
        stdout, stderr, rc = self._run(["wg-quick", "down", self.interface])
        if rc == 0:
            return True, f"{self.interface} остановлен"
        self._run(["ip", "link", "set", self.interface, "down"])
        return True, f"{self.interface} остановлен (ручной метод)"

    def restart(self) -> tuple:
        self.stop()
        return self.start()

    def get_configured_allowed_ips(self) -> list:
        if not self.has_config():
            return []
        try:
            with open(self.config_path, "r") as f:
                content = f.read()
        except IOError:
            return []
        ips = []
        for line in content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("AllowedIPs"):
                value = line_stripped.split("=", 1)[1].strip()
                for cidr in value.split(","):
                    cidr = cidr.strip()
                    if cidr and cidr != "0.0.0.0/0" and cidr != "::/0":
                        ips.append(cidr)
        return ips

    def get_public_key(self) -> str:
        stdout, _, rc = self._run(["wg", "show", self.interface, "public-key"])
        if rc == 0:
            return stdout.strip()
        return ""