# pi_vpn_split — DNS-based VPN Split Tunnelling

Route traffic to specific domains (YouTube, Telegram, ChatGPT) through WireGuard VPN without affecting the rest of your network traffic.

## Architecture

```
Client → AdGuard Home (:53) → DNS-VPN Gateway (:5353) → resolves managed domains → adds point-to-point routes via wg0 → only matching IPs go through VPN
```

## Requirements

- **Raspberry Pi** or any Linux host with Docker
- **WireGuard config** from your VPN provider (set `AllowedIPs = 0.0.0.0/0, ::/0`)
- Docker + Docker Compose installed

## Quick Start (one-line host setup)

```bash
# 1. Run host setup (ip_forward, iptables, ipset, systemd-resolved, etc.)
sudo bash host_setup.sh

# 2. Create WireGuard config directory and place your config
sudo mkdir -p /etc/wireguard
# IMPORTANT: Save your WG config to /etc/wireguard/wg0.conf
# Keep AllowedIPs = 0.0.0.0/0, ::/0 — the script will clean up unwanted routes

# 3. Start services
docker compose pull && docker compose up -d

# 4. Complete AdGuard Home setup at http://YOUR_PI_IP:3000
#    - Web interface: 0.0.0.0:3000
#    - DNS port: 53
#    - Upstream DNS: 127.0.0.1:5353
#    - Bootstrap DNS: 8.8.8.8, 1.1.1.1

# 5. Open DNS-VPN Gateway at http://YOUR_PI_IP:3001
#    - Upload your WG config (if not already in /etc/wireguard/wg0.conf)
#    - Click "+ YouTube", "+ Telegram", "+ ChatGPT"
#    - Your clients should now get DNS from AdGuard, and traffic to managed domains goes through VPN
```

## WireGuard Config Note

Your `wg0.conf` **must** include `AllowedIPs = 0.0.0.0/0, ::/0`. This is required for the VPN server to accept the connection. The `dns-vpn-gateway` service on startup will automatically remove `wg-quick` routing rules that would redirect all traffic through the VPN. Only IPs of managed domains will be routed through wg0.

Do **NOT** set `DNS = ...` in your WG config — DNS is handled by AdGuard Home.

## Ports

| Service | Port | Description |
|---|---|---|
| AdGuard Home | :53 (UDP) | DNS server for clients |
| AdGuard Home | :80 (TCP) | AdGuard web UI |
| DNS-VPN Gateway | :3001 (TCP) | Domain management web UI |
| DNS-VPN Gateway | :5353 (UDP) | DNS upstream for AdGuard |

## Manual Setup (without host_setup.sh)

```bash
# Enable IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-ipforward.conf

# Allow packet forwarding in iptables
sudo iptables -P FORWARD ACCEPT

# Create ipset
sudo ipset create vpn_domains hash:net family inet 2>/dev/null || true

# Add iptables mangle rules
sudo iptables -t mangle -A PREROUTING -m set --match-set vpn_domains dst -j MARK --set-mark 0x01
sudo iptables -t mangle -A FORWARD -m set --match-set vpn_domains dst -j MARK --set-mark 0x01

# Setup policy routing
sudo ip route replace default dev wg0 table 100
sudo ip rule add fwmark 0x1 table 100 priority 4000

# Stop systemd-resolved (frees port 53)
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

## GitHub Container Registry

The Docker image is automatically built for `linux/arm64` and published to:

```
ghcr.io/buger68/pi_vpn_split:latest
```

## License

MIT
---

# 🇷🇺 pi_vpn_split — Разделение трафика через DNS

Направляйте трафик к определённым доменам (YouTube, Telegram, ChatGPT) через WireGuard VPN, не затрагивая остальной интернет.

## Архитектура

```
Клиент → AdGuard Home (:53) → DNS-VPN Gateway (:5353) → определяет управляемые домены → добавляет точечные маршруты через wg0 → только эти IP идут через VPN
```

## Быстрый старт (одна команда)

```bash
# 1. Настройка хоста (ip_forward, iptables, ipset, отключение systemd-resolved)
sudo bash host_setup.sh

# 2. Конфиг WireGuard
sudo mkdir -p /etc/wireguard
# Сохраните свой WG конфиг в /etc/wireguard/wg0.conf
# AllowedIPs = 0.0.0.0/0, ::/0 — ОБЯЗАТЕЛЬНО оставить, иначе сервер не примет соединение
# DNS = ... в конфиге НЕ СТАВИТЬ — DNS работает через AdGuard

# 3. Запуск
docker compose pull && docker compose up -d

# 4. Настройка AdGuard Home на http://АДРЕС_МАЛИНКИ:3000
#    - Веб-интерфейс: 0.0.0.0:3000
#    - DNS порт: 53
#    - Upstream DNS: 127.0.0.1:5353
#    - Bootstrap DNS: 8.8.8.8, 1.1.1.1

# 5. Откройте DNS-VPN Gateway на http://АДРЕС_МАЛИНКИ:3001
#    - Загрузите конфиг WG (если ещё не в /etc/wireguard/wg0.conf)
#    - Нажмите "+ YouTube", "+ Telegram", "+ ChatGPT"
```

## Важно про WireGuard

В конфиге `wg0.conf` **обязательно** должен быть `AllowedIPs = 0.0.0.0/0, ::/0` — без этого VPN-сервер не примет подключение. При старте `dns-vpn-gateway` сам удалит правила wg-quick, которые направляют весь трафик через VPN. Только IP управляемых доменов пойдут через wg0.

**Не ставьте `DNS = ...`** в конфиге WG — DNS обслуживается AdGuard Home.

## Порты

| Сервис | Порт | Назначение |
|---|---|---|
| AdGuard Home | :53 (UDP) | DNS для клиентов |
| AdGuard Home | :80 (TCP) | Веб-интерфейс AdGuard |
| DNS-VPN Gateway | :3001 (TCP) | Управление доменами |
| DNS-VPN Gateway | :5353 (UDP) | DNS upstream для AdGuard |

## Ручная настройка (без host_setup.sh)

```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -P FORWARD ACCEPT
sudo ipset create vpn_domains hash:net family inet 2>/dev/null || true
sudo iptables -t mangle -A PREROUTING -m set --match-set vpn_domains dst -j MARK --set-mark 0x01
sudo iptables -t mangle -A FORWARD -m set --match-set vpn_domains dst -j MARK --set-mark 0x01
sudo ip route replace default dev wg0 table 100
sudo ip rule add fwmark 0x1 table 100 priority 4000
sudo systemctl stop systemd-resolved && sudo systemctl disable systemd-resolved
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

## GitHub Container Registry

Образ автоматически собирается для `linux/arm64` и публикуется в:

```
ghcr.io/buger68/pi_vpn_split:latest
```
