#!/usr/bin/env bash

# Exit on error
set -e

# Static IP parameters
WIRED_IP="192.168.10.222/24"
WIFI_IP="192.168.10.223/24"
GATEWAY="192.168.10.1"
LOCAL_DNS="127.0.0.1"

echo "=================================================================="
echo "  Local Network Static IP & DNS Resolver Setup Script"
echo "  Target Hostname/Domain: strixly.nuclear.cooking"
echo "=================================================================="

# Check root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run with sudo privileges."
  echo "Usage: sudo ./setup_network.sh"
  exit 1
fi

# Detect active connections
echo "[-] Detecting active NetworkManager connection profiles..."
WIRED_CONN=$(nmcli -t -f NAME,TYPE connection show --active | grep ethernet | head -n1 | cut -d: -f1)
WIFI_CONN=$(nmcli -t -f NAME,TYPE connection show --active | grep wireless | head -n1 | cut -d: -f1)

WIRED_CONFIGURED=false
WIFI_CONFIGURED=false

# Configure Wired Ethernet
if [ -n "$WIRED_CONN" ]; then
  echo "[+] Found active Ethernet connection: '$WIRED_CONN'"
  read -p "    Configure static IP $WIRED_IP on '$WIRED_CONN'? (y/N): " -n 1 -r
  echo ""
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    nmcli connection modify "$WIRED_CONN" \
      ipv4.addresses "$WIRED_IP" \
      ipv4.gateway "$GATEWAY" \
      ipv4.dns "$LOCAL_DNS" \
      ipv4.method "manual"
    echo "    [✓] Ethernet static IP configured."
    WIRED_CONFIGURED=true
  else
    echo "    [!] Skipping Ethernet static IP configuration."
  fi
else
  echo "[!] No active Ethernet connection profile detected."
fi

# Configure Wi-Fi
if [ -n "$WIFI_CONN" ]; then
  echo "[+] Found active Wi-Fi connection: '$WIFI_CONN'"
  read -p "    Configure static IP $WIFI_IP on '$WIFI_CONN'? (y/N): " -n 1 -r
  echo ""
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    nmcli connection modify "$WIFI_CONN" \
      ipv4.addresses "$WIFI_IP" \
      ipv4.gateway "$GATEWAY" \
      ipv4.dns "$LOCAL_DNS" \
      ipv4.method "manual"
    echo "    [✓] Wi-Fi static IP configured."
    WIFI_CONFIGURED=true
  else
    echo "    [!] Skipping Wi-Fi static IP configuration."
  fi
else
  echo "[!] No active Wi-Fi connection profile detected."
fi

# Configure dnsmasq if requested
echo ""
read -p "Configure local dnsmasq resolver for strixly.nuclear.cooking? (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  DNSMASQ_CONF="/etc/dnsmasq.d/strixly.conf"
  echo "[-] Writing dnsmasq config to $DNSMASQ_CONF..."
  
  WIRED_DEV=$(nmcli -t -f DEVICE,TYPE connection show --active | grep ethernet | head -n1 | cut -d: -f1)
  WIFI_DEV=$(nmcli -t -f DEVICE,TYPE connection show --active | grep wireless | head -n1 | cut -d: -f1)

  cat <<EOF > "$DNSMASQ_CONF"
# Configuration for strixly.nuclear.cooking
# Listen only on specified interfaces and local loopback address
$( [ -n "$WIRED_DEV" ] && echo "interface=$WIRED_DEV" )
$( [ -n "$WIFI_DEV" ] && echo "interface=$WIFI_DEV" )
listen-address=127.0.0.1
bind-dynamic

# Domain mapping
address=/strixly.nuclear.cooking/192.168.10.222
address=/strixly-wifi.nuclear.cooking/192.168.10.223

# Upstream DNS forwarding
server=1.1.1.1
server=8.8.8.8
EOF

  echo "[-] Enabling and restarting dnsmasq systemd service..."
  systemctl enable dnsmasq
  systemctl restart dnsmasq
  echo "    [✓] dnsmasq configured and restarted."
else
  echo "[!] Skipping dnsmasq resolver configuration."
fi

echo ""
echo "=================================================================="
echo "  Configuration Finished!"
echo "=================================================================="
echo "To apply your static IP configurations, restart your connections:"
if [ "$WIRED_CONFIGURED" = true ]; then
  echo "  sudo nmcli connection up \"$WIRED_CONN\""
fi
if [ "$WIFI_CONFIGURED" = true ]; then
  echo "  sudo nmcli connection up \"$WIFI_CONN\""
fi
echo ""
echo "Note: If you configured dnsmasq, other devices on your home network"
echo "can access 'strixly.nuclear.cooking' by setting their DNS server"
echo "to this machine's IP (192.168.10.222)."
echo "=================================================================="
