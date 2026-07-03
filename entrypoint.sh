#!/bin/bash
set -e

echo "=== DNS-VPN Gateway Entrypoint ==="

# Включаем ip_forward (нужен для NAT)
sysctl -w net.ipv4.ip_forward=1 > /dev/null

# Если передан WG_CONFIG в переменной окружения — сохраняем его
if [ -n "$WG_CONFIG" ]; then
    mkdir -p /etc/wireguard
    echo "$WG_CONFIG" > /etc/wireguard/wg0.conf
    chmod 600 /etc/wireguard/wg0.conf
    echo "[entrypoint] WG конфиг сохранён из WG_CONFIG"
fi

# Если конфиг wg0.conf существует — поднимаем WireGuard
if [ -f /etc/wireguard/wg0.conf ]; then
    echo "[entrypoint] Запуск WireGuard..."
    wg-quick up wg0 2>&1 || true
    # Чистим правила wg-quick, которые весь трафик направляют через wg0
    ip rule del priority 4999 2>/dev/null || true
    ip rule del priority 4998 2>/dev/null || true
    ip route flush table 51820 2>/dev/null || true
fi

echo "[entrypoint] Запуск Python-приложения..."
exec "$@"