import os

# Порт для веб-интерфейса
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")

# Порт для DNS-сервера
DNS_PORT = int(os.getenv("DNS_PORT", "53"))
DNS_HOST = os.getenv("DNS_HOST", "0.0.0.0")

# VPN интерфейс
VPN_INTERFACE = os.getenv("VPN_INTERFACE", "wg0")

# Внешний DNS для резолвинга неуправляемых доменов (используется для fallback)
UPSTREAM_DNS = os.getenv("UPSTREAM_DNS", "8.8.8.8")

# DoH upstream (основной, зашифрованный)
UPSTREAM_DOH_URL = os.getenv("UPSTREAM_DOH_URL", "https://dns.quad9.net/dns-query")

# Интервал ре-резолвинга управляемых доменов (в секундах)
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "300"))

# Файл для хранения управляемых доменов (сохраняем настройки)
DATA_FILE = os.path.join(os.path.dirname(__file__), "domains.json")