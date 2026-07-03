import json
import os
from config import DATA_FILE

class DomainStore:
    """Хранение управляемых доменов и их кэшированных IP-адресов"""

    def __init__(self):
        self.domains = {}  # domain -> {ip: route_added}
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    self.domains = json.load(f)
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

    def add_ip_for_domain(self, domain: str, ip: str):
        """Добавить IP к управляемому домену (с учётом wildcard)"""
        managed = self._find_managed_domain(domain)
        if managed and ip not in self.domains[managed]:
            self.domains[managed][ip] = False
            self.save()
            return True
        return False

    def mark_route_added(self, domain: str, ip: str):
        """Отметить, что маршрут для IP добавлен"""
        managed = self._find_managed_domain(domain)
        if managed and ip in self.domains[managed]:
            self.domains[managed][ip] = True
            self.save()

    def get_domain_ips(self, domain: str):
        domain = domain.strip().lower()
        if domain in self.domains:
            return list(self.domains[domain].keys())
        return []

    def is_managed(self, domain: str) -> bool:
        """Проверяет, управляется ли домен (точное совпадение или wildcard)"""
        return self._find_managed_domain(domain) is not None