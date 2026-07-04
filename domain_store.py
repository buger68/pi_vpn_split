import json
import os
import time
from config import DATA_FILE

class DomainStore:
    """Хранение управляемых доменов и их кэшированных IP-адресов"""

    def __init__(self):
        self.domains = {}  # domain -> {"ips": {"ip": {"route_added": bool, "ttl": int, "last_resolved": float}}}
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    raw = json.load(f)
                # Нормализация старого формата (если домен -> {ip: bool})
                self.domains = {}
                for domain, value in raw.items():
                    if isinstance(value, dict):
                        ips = {}
                        for k, v in value.items():
                            if isinstance(v, bool):
                                ips[k] = {"route_added": v, "ttl": 300, "last_resolved": 0}
                            elif isinstance(v, dict):
                                ips[k] = {
                                    "route_added": v.get("route_added", False),
                                    "ttl": v.get("ttl", 300),
                                    "last_resolved": v.get("last_resolved", 0)
                                }
                        self.domains[domain] = ips
                    else:
                        self.domains[domain] = value
            except (json.JSONDecodeError, IOError):
                self.domains = {}

    def save(self):
        dirname = os.path.dirname(DATA_FILE)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(self.domains, f, indent=2)

    def add_domain(self, domain: str):
        domain = domain.strip().lower()
        if domain not in self.domains:
            self.domains[domain] = {}
            self.save()
            return True
        return False

    def remove_domain(self, domain: str):
        domain = domain.strip().lower()
        if domain in self.domains:
            ips = dict(self.domains[domain])
            del self.domains[domain]
            self.save()
            # Возвращаем список IP (ключей), для удаления маршрутов
            return ips
        return {}

    def list_domains(self):
        return list(self.domains.keys())

    def _find_managed_domain(self, domain: str) -> str:
        """Найти управляемый домен (точный или wildcard), к которому относится domain"""
        domain = domain.strip().lower()
        if domain in self.domains:
            return domain
        # Проверка wildcard
        parts = domain.split(".")
        for i in range(1, len(parts)):
            wildcard = "*." + ".".join(parts[i:])
            if wildcard in self.domains:
                return wildcard
        return None

    def add_ip_for_domain(self, domain: str, ip: str, ttl: int = 300):
        """Добавить IP к управляемому домену (с учётом wildcard)"""
        managed = self._find_managed_domain(domain)
        if managed and ip not in self.domains[managed]:
            self.domains[managed][ip] = {
                "route_added": False,
                "ttl": ttl,
                "last_resolved": time.time()
            }
            self.save()
            return True
        return False

    def update_ip_ttl(self, domain: str, ip: str, ttl: int):
        """Обновить TTL и время последнего разрешения для IP"""
        managed = self._find_managed_domain(domain)
        if managed and ip in self.domains.get(managed, {}):
            self.domains[managed][ip]["ttl"] = ttl
            self.domains[managed][ip]["last_resolved"] = time.time()
            self.save()

    def mark_route_added(self, domain: str, ip: str):
        """Отметить, что маршрут для IP добавлен"""
        managed = self._find_managed_domain(domain)
        if managed and ip in self.domains.get(managed, {}):
            self.domains[managed][ip]["route_added"] = True
            self.save()

    def get_domain_ips(self, domain: str):
        domain = domain.strip().lower()
        if domain in self.domains:
            return list(self.domains[domain].keys())
        return []

    def get_domain_ips_with_meta(self, domain: str):
        """Вернуть IP с мета-данными (ttl, last_resolved, route_added)"""
        domain = domain.strip().lower()
        if domain in self.domains:
            return dict(self.domains[domain])
        return {}

    def is_managed(self, domain: str) -> bool:
        """Проверяет, управляется ли домен (точное совпадение или wildcard)"""
        return self._find_managed_domain(domain) is not None

    def is_stale(self, domain: str, ip: str, margin: int = 60) -> bool:
        """Проверить, устарел ли IP адрес домена по TTL"""
        managed = self._find_managed_domain(domain)
        if managed and ip in self.domains.get(managed, {}):
            info = self.domains[managed][ip]
            elapsed = time.time() - info.get("last_resolved", 0)
            return elapsed > (info.get("ttl", 300) + margin)
        return True

    def get_all_managed_ips(self, only_with_routes: bool = False) -> set:
        """Получить все IP управляемых доменов"""
        ips = set()
        for domain, ip_dict in self.domains.items():
            for ip, info in ip_dict.items():
                if only_with_routes and not info.get("route_added", False):
                    continue
                ips.add(ip)
        return ips

    def get_domains_needing_refresh(self) -> list:
        """Вернуть список доменов, у которых есть IP нуждающиеся в обновлении"""
        now = time.time()
        result = []
        for domain, ip_dict in self.domains.items():
            if not ip_dict:
                result.append(domain)
                continue
            for ip, info in ip_dict.items():
                elapsed = now - info.get("last_resolved", 0)
                if elapsed > (info.get("ttl", 300) + 60):
                    result.append(domain)
                    break
        return result

    def get_ip_set(self) -> set:
        """Вернуть все IP (без domain)"""
        result = set()
        for ip_dict in self.domains.values():
            for ip in ip_dict:
                result.add(ip)
        return result