# pi_vpn_split — DNS-VPN Gateway

DNS-based VPN split tunnelling for Raspberry Pi / Docker.

**Architecture:**
```
Client → AdGuard Home (:53) → dns-vpn-gateway (:5353) → identifies managed domains → adds routes via wg0
```

## Quick start (Docker)

```bash
# 1. Place WireGuard config
sudo cp /etc/wireguard/wg0.conf .

# 2. Start
docker compose up -d
```

## Ports
| Service | Port | Description |
|---|---|---|
| AdGuard Home | :3000 | Web UI / Initial setup |
| DNS-VPN Gateway | :3001 | Web UI / Domain management |
| DNS upstream | :5353 | Upstream for AdGuard |
| DNS | :53 | AdGuard DNS |

## Build locally
```bash
docker build -t dns-vpn-gateway:latest .
```

## Environment
- `DNS_PORT=5353` — upstream DNS port
- `WEB_PORT=3001` — web UI port
- `WG_CONFIG` — WireGuard config content (optional)
- `VPN_INTERFACE=wg0`