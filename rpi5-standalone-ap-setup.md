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
channel=7

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

Enable hostapd to start on boot:

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
```

## Step 6: Disable wpa_supplicant for wlan0

To prevent wpa_supplicant from trying to connect wlan0 to other networks:

```bash
sudo systemctl mask wpa_supplicant.service
sudo systemctl stop wpa_supplicant.service
```

## Step 7: Create Startup Script

Create a startup script to ensure everything starts correctly:

```bash
sudo nano /usr/local/bin/ap-startup.sh
```

Add the following content:

```bash
#!/bin/bash
# Access Point startup script

# Wait for network interfaces to be up
sleep 10

# Make sure wlan0 is up and in the correct mode
ip link set wlan0 down
ip link set wlan0 up

# Check if hostapd is running, if not start it
if ! systemctl is-active --quiet hostapd; then
    systemctl restart hostapd
fi

# Check if dnsmasq is running, if not start it
if ! systemctl is-active --quiet dnsmasq; then
    systemctl restart dnsmasq
fi

# Log the startup
echo "Access point startup script executed at $(date)" >> /var/log/ap-startup.log
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
Wants=hostapd.service dnsmasq.service

[Service]
Type=oneshot
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

## Step 8: Create a systemd override for hostapd

```bash
sudo mkdir -p /etc/systemd/system/hostapd.service.d/
sudo nano /etc/systemd/system/hostapd.service.d/override.conf
```

Add the following content:

```
[Unit]
After=systemd-networkd.service
```

Save and exit (Ctrl+O, Enter, Ctrl+X)

Reload systemd to recognize the changes:

```bash
sudo systemctl daemon-reload
```

## Step 9: Start Services and Test

Start all the services:

```bash
sudo systemctl start dnsmasq
sudo systemctl start hostapd
sudo systemctl start ap-startup.service
```

Check the status of all services:

```bash
sudo systemctl status systemd-networkd
sudo systemctl status hostapd
sudo systemctl status dnsmasq
sudo systemctl status ap-startup.service
```

Verify wlan0 is in AP mode:

```bash
sudo iw dev wlan0 info
```

You should see "type AP" in the output.

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

### Check if RF kill is blocking the wireless:
```bash
sudo rfkill list
```

If wlan0 is blocked, unblock it:
```bash
sudo rfkill unblock all
```

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

### Enable 5GHz (if supported by your hardware):
Edit `/etc/hostapd/hostapd.conf` and change:
```
hw_mode=a
channel=36
```