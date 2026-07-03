#!/bin/bash
set -e

echo "=========================================="
echo "  pi_vpn_split — Host Setup Script"
echo "=========================================="
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)."
    exit 1
fi

# 1. Enable IP forwarding
echo "➡️  Enabling net.ipv4.ip_forward..."
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-ipforward.conf
sysctl -w net.ipv4.ip_forward=1 > /dev/null
echo "   ✅ OK"

# 2. Set iptables FORWARD policy to ACCEPT
echo "➡️  Setting iptables FORWARD policy to ACCEPT..."
iptables -P FORWARD ACCEPT 2>/dev/null || true
echo "   ✅ OK"

# 3. Stop systemd-resolved (frees port 53)
echo "➡️  Stopping systemd-resolved..."
systemctl stop systemd-resolved 2>/dev/null || true
systemctl disable systemd-resolved 2>/dev/null || true
echo "   ✅ OK"

# 4. Set /etc/resolv.conf
echo "➡️  Setting /etc/resolv.conf to 8.8.8.8..."
rm -f /etc/resolv.conf
echo "nameserver 8.8.8.8" > /etc/resolv.conf
echo "nameserver 1.1.1.1" >> /etc/resolv.conf
echo "   ✅ OK"

# 5. Create ipset for VPN domains (if doesn't exist)
echo "➡️  Creating ipset 'vpn_domains'..."
ipset create vpn_domains hash:net family inet 2>/dev/null || echo "   (already exists, skipping)"
echo "   ✅ OK"

# 6. Add iptables mangle rules (mark traffic to vpn_domains with fwmark 0x1)
echo "➡️  Adding iptables mangle rules..."
iptables -t mangle -C PREROUTING -m set --match-set vpn_domains dst -j MARK --set-mark 0x01 2>/dev/null || \
    iptables -t mangle -A PREROUTING -m set --match-set vpn_domains dst -j MARK --set-mark 0x01
iptables -t mangle -C FORWARD -m set --match-set vpn_domains dst -j MARK --set-mark 0x01 2>/dev/null || \
    iptables -t mangle -A FORWARD -m set --match-set vpn_domains dst -j MARK --set-mark 0x01
echo "   ✅ OK"

# 7. Add policy routing
echo "➡️  Setting up policy routing..."
ip route replace default dev wg0 table 100 2>/dev/null || true
ip rule del fwmark 0x1 table 100 2>/dev/null || true
ip rule add fwmark 0x1 table 100 priority 4000 2>/dev/null || true
echo "   ✅ OK"

# 8. Save iptables rules for persistence (with iptables-persistent if available)
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save 2>/dev/null || true
    echo "   ✅ iptables rules saved (netfilter-persistent)"
elif command -v iptables-save &>/dev/null; then
    mkdir -p /etc/iptables
    iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
    echo "   ✅ iptables rules saved to /etc/iptables/rules.v4"
fi

# 9. Create docker compose directory and pull latest
echo ""
echo "=========================================="
echo "  ✅ Host setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Clone the repo:  git clone https://github.com/buger68/pi_vpn_split.git"
echo "  2. cd pi_vpn_split"
echo "  3. Place your WG config:  sudo cp /path/to/wg0.conf ./"
echo "  4. Start:  docker compose pull && docker compose up -d"
echo "  5. Complete AdGuard setup at http://$(hostname -I | awk '{print $1}'):3000"
echo ""