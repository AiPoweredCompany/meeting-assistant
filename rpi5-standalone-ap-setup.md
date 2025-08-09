# Raspberry Pi 5 Standalone Access Point Setup Guide

This guide will help you configure your Raspberry Pi 5 as a standalone Wi-Fi access point that automatically starts on boot. This setup creates a local network without internet connectivity, allowing devices like smartphones to connect directly to the Raspberry Pi.

## Prerequisites

- Raspberry Pi 5
- MicroSD card with fresh Raspberry Pi OS installation (Debian 12 Bookworm)
- Wi-Fi adapter (built-in or external USB)
- Power supply (3.0A+ recommended)
- SSH access or keyboard/monitor connected to the Raspberry Pi

## Step 1: Initial Setup

1. Flash a fresh copy of Raspberry Pi OS (Bookworm) to your microSD card
2. Boot your Raspberry Pi and complete the initial setup
3. Update your system:

```bash
sudo apt update
sudo apt upgrade -y
```

## Step 2: Install Required Software

Install the necessary packages:

```bash
sudo apt install hostapd dnsmasq -y
```

Stop the services initially while we configure them:

```bash
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
```

## Step 3: Configure Network Interfaces

### 3.1. Configure Static IP for wlan0

Edit the dhcpcd configuration file:

```bash
sudo nano /etc/dhcpcd.conf
```

Add the following lines at the end of the file:

```
# Configuration for wlan0 as access point
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

### 3.2. Create systemd-networkd Configuration

Create a directory for network configurations if it doesn't exist:

```bash
sudo mkdir -p /etc/systemd/network/
```

Create a network configuration file for wlan0:

```bash
sudo nano /etc/systemd/network/12-wlan0.network
```

Add the following content:

```
[Match]
Name=wlan0

[Network]
Address=192.168.4.1/24
DHCPServer=yes

[DHCPServer]
PoolOffset=10
PoolSize=50
EmitDNS=yes
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

### 3.3. Apply Network Changes

Enable and start systemd-networkd:

```bash
sudo systemctl enable systemd-networkd
sudo systemctl start systemd-networkd
```

## Step 4: Configure DHCP Server (dnsmasq)

Back up the original dnsmasq configuration:

```bash
sudo cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
```

Create a new dnsmasq configuration:

```bash
sudo nano /etc/dnsmasq.conf
```

Clear the file contents and add:

```
# Interface to bind to
interface=wlan0
# Specify the DHCP range
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
# Domain name
domain=local
# DHCP options
dhcp-option=option:router,192.168.4.1
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

Enable dnsmasq to start on boot:

```bash
sudo systemctl enable dnsmasq
```

## Step 5: Configure Wi-Fi Access Point (hostapd)

Create hostapd configuration file:

```bash
sudo nano /etc/hostapd/hostapd.conf
```

Add the following content (adjust parameters as needed):

```
# Interface configuration
interface=wlan0
driver=nl80211

# SSID configuration
ssid=RaspberryPi_AP
country_code=US  # Change to your country code

# Hardware mode (g = IEEE 802.11g)
hw_mode=g
channel=1

# MAC address access control
macaddr_acl=0

# Authentication options
auth_algs=1

# WPA options
wpa=2
wpa_passphrase=raspberry  # Change this to your preferred password
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP

# 802.11n support
ieee80211n=0  # Disable 802.11n for better compatibility
wmm_enabled=0  # Disable WMM for better compatibility
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

Configure hostapd default file:

```bash
sudo nano /etc/default/hostapd
```

Find the line with `#DAEMON_CONF=""` and change it to:

```
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

## Step 6: Disable wpa_supplicant and Create Custom hostapd Service

To prevent wpa_supplicant from trying to connect wlan0 to other networks:

```bash
sudo systemctl mask wpa_supplicant.service
sudo systemctl stop wpa_supplicant.service
```

Create a custom hostapd service that runs directly in debug mode for better reliability:

```bash
sudo nano /etc/systemd/system/hostapd-custom.service
```

Add this content:

```
[Unit]
Description=Hostapd IEEE 802.11 AP
After=network.target systemd-networkd.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 5
ExecStartPre=/bin/ip link set wlan0 down
ExecStartPre=/bin/ip link set wlan0 up
ExecStart=/usr/sbin/hostapd -dd /etc/hostapd/hostapd.conf
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

Disable the original hostapd service and enable our custom one:

```bash
sudo systemctl disable hostapd
sudo systemctl enable hostapd-custom.service
```

## Step 7: Create Startup Script

Create a startup script to ensure everything starts correctly:

```bash
sudo nano /usr/local/bin/ap-startup.sh
```

Add the following content:

```bash
#!/bin/bash
# Simple AP startup script

# Unblock wireless
rfkill unblock wifi

# Configure wlan0
ip link set wlan0 down
sleep 2

# Force AP mode with explicit channel
iw dev wlan0 set type __ap
sleep 1
iw dev wlan0 set channel 1
sleep 1

# Bring up interface
ip link set wlan0 up
sleep 2

# Start dnsmasq if not running
if ! systemctl is-active --quiet dnsmasq; then
    systemctl restart dnsmasq
fi

# Log the startup
echo "AP startup script executed at $(date)" >> /var/log/ap-startup.log
```

Make the script executable:

```bash
sudo chmod +x /usr/local/bin/ap-startup.sh
```

Create a systemd service for the startup script:

```bash
sudo nano /etc/systemd/system/ap-startup.service
```

Add the following content:

```
[Unit]
Description=Access Point Startup Script
After=network.target systemd-networkd.service
Before=hostapd-custom.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/ap-startup.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

Enable the service:

```bash
sudo systemctl enable ap-startup.service
```

## Step 8: Reload systemd and Enable Services

Reload systemd to recognize all the changes:

```bash
sudo systemctl daemon-reload
```

Make sure all services are enabled to start on boot:

```bash
sudo systemctl enable systemd-networkd
sudo systemctl enable dnsmasq
sudo systemctl enable ap-startup.service
sudo systemctl enable hostapd-custom.service
```

## Step 9: Start Services and Test

Start all the services in the correct order:

```bash
sudo systemctl restart systemd-networkd
sudo systemctl restart ap-startup.service
sudo systemctl restart hostapd-custom.service
sudo systemctl restart dnsmasq
```

Check the status of all services:

```bash
sudo systemctl status systemd-networkd
sudo systemctl status ap-startup.service
sudo systemctl status hostapd-custom.service
sudo systemctl status dnsmasq
```

Verify wlan0 is in AP mode:

```bash
sudo iw dev wlan0 info
```

You should see "type AP" in the output and the channel should be set to 1.

## Step 10: Test from Another Device

1. On a smartphone or tablet:
   - Go to Wi-Fi settings
   - Look for the SSID "RaspberryPi_AP"
   - Connect using the password you set in hostapd.conf (default: raspberry)

2. Once connected, verify:
   - The device gets an IP address in the 192.168.4.x range
   - You can ping the Raspberry Pi at 192.168.4.1
   - You can SSH to the Raspberry Pi using its IP address (if SSH is enabled)

## Step 11: Reboot Test

Reboot your Raspberry Pi to ensure everything starts automatically:

```bash
sudo reboot
```

After the Raspberry Pi reboots:
1. Wait a minute or two for all services to start
2. Try connecting to the access point from another device
3. Verify you can communicate with the Raspberry Pi

## Troubleshooting

### If RF-kill is blocking the wireless:

Check if RF kill is blocking the wireless:
```bash
sudo rfkill list
```

If wlan0 is blocked, unblock it:
```bash
sudo rfkill unblock all
```

### If the access point doesn't appear:

Check hostapd status:
```bash
sudo systemctl status hostapd
```

Check hostapd logs:
```bash
sudo journalctl -u hostapd
```

### If devices can't get IP addresses:

Check dnsmasq status:
```bash
sudo systemctl status dnsmasq
```

Check dnsmasq logs:
```bash
sudo journalctl -u dnsmasq
```

### If wlan0 is not in AP mode:

Check if wpa_supplicant is running:
```bash
sudo systemctl status wpa_supplicant
```

If it's active, stop and disable it:
```bash
sudo systemctl stop wpa_supplicant
sudo systemctl mask wpa_supplicant
```

Manually set wlan0 to AP mode and restart hostapd:
```bash
sudo ip link set wlan0 down
sudo iw dev wlan0 set type __ap
sudo iw dev wlan0 set channel 1
sudo ip link set wlan0 up
sudo systemctl restart hostapd-custom.service
```

### If hostapd fails to start after reboot:

Check the logs for any errors:
```bash
sudo journalctl -u hostapd-custom.service
```

Try running hostapd manually with debug output:
```bash
sudo hostapd -dd /etc/hostapd/hostapd.conf
```

This will show detailed output about what's preventing hostapd from starting.

## Additional Notes

1. This setup creates a standalone access point without internet connectivity
2. To access the Raspberry Pi from connected devices, use its IP address (192.168.4.1)
3. You can run web servers, SSH, or other services on the Raspberry Pi that can be accessed from connected devices
4. To change the SSID or password, edit `/etc/hostapd/hostapd.conf` and restart hostapd

## Customization Options

### Change the network IP range:
Edit `/etc/dhcpcd.conf` and `/etc/systemd/network/12-wlan0.network` to use a different IP range than 192.168.4.x

### Change the Wi-Fi channel:
Edit `/etc/hostapd/hostapd.conf` and modify the `channel` parameter (1-11 for 2.4GHz)

Note: Channel 1 is recommended for better compatibility with most devices

### Enable 5GHz (if supported by your hardware):
Edit `/etc/hostapd/hostapd.conf` and change:
```
hw_mode=a
channel=36
```