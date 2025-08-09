# Raspberry Pi 5 Web Server Setup Guide

This guide will help you set up a lightweight web server on your Raspberry Pi 5 that will automatically start after your access point is running. This setup will serve the `index.html` file from your Raspberry Pi, allowing mobile devices connected to your Pi's access point to access the web page.

## Prerequisites

- Raspberry Pi 5 with Raspberry Pi OS (Bookworm)
- Access point already configured and working (as per `rpi5-standalone-ap-setup.md`)
- AP startup script created and enabled (as configured in the previous steps)
- The `index.html` file you want to serve

## Step 1: Choose and Install a Web Server

For a lightweight solution, we'll use Nginx as our web server:

```bash
sudo apt update
sudo apt install nginx -y
```

## Step 2: Configure Nginx

1. Stop the Nginx service before configuring:

```bash
sudo systemctl stop nginx
```

2. Create a backup of the default Nginx configuration:

```bash
sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.backup
```

3. Edit the default Nginx configuration:

```bash
sudo nano /etc/nginx/sites-available/default
```

4. Replace the content with this simplified configuration:

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    root "/home/olivier/Documents/AI powered company/meeting-notes/meeting-assistant";
    index index.html;

    server_name _;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

5. Save and exit (Ctrl+O, Enter, Ctrl+X)

## Step 3: Test the Nginx Configuration

Check if the configuration is valid:

```bash
sudo nginx -t
```

If you see "syntax is ok" and "test is successful", proceed to the next step.

## Step 4: Create a Systemd Service to Start Nginx After the Access Point

1. Create a new systemd service file:

```bash
sudo nano /etc/systemd/system/nginx-after-ap.service
```

2. Add the following content:

```
[Unit]
Description=Start Nginx after Access Point
After=ap-startup.service hostapd.service
Requires=ap-startup.service
Wants=hostapd.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 10
ExecStart=/bin/systemctl start nginx
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

3. Save and exit (Ctrl+O, Enter, Ctrl+X)

4. Enable the new service to start on boot:

```bash
sudo systemctl enable nginx-after-ap.service
```

## Step 5: Start the Services

1. Start the Nginx service:

```bash
sudo systemctl start nginx
```

2. Start our custom service:

```bash
sudo systemctl start nginx-after-ap.service
```

## Step 6: Check Service Status

Verify that both services are running correctly:

```bash
sudo systemctl status nginx
sudo systemctl status nginx-after-ap.service
```

## Step 7: Reboot and Test

1. Reboot your Raspberry Pi:

```bash
sudo reboot
```

2. After the Raspberry Pi reboots:
   - Wait for the access point to start (1-2 minutes)
   - Connect a mobile device to the "meeting-assistant" Wi-Fi network (or whatever SSID you configured)
   - Open a web browser on the mobile device
   - Navigate to `http://192.168.4.1`
   - You should see your web page load

3. If the access point doesn't appear after reboot:
   - SSH into your Raspberry Pi
   - Check the status of the services:
   ```bash
   sudo systemctl status ap-startup.service
   sudo systemctl status hostapd
   sudo systemctl status dnsmasq
   ```
   - If hostapd is failing, manually run the startup script:
   ```bash
   sudo /usr/local/bin/ap-startup.sh
   ```

## Troubleshooting

### If the access point doesn't start after reboot:

1. Check if RF kill is blocking the wireless:
```bash
sudo rfkill list
```

2. If blocked, unblock it:
```bash
sudo rfkill unblock all
```

3. Check hostapd status:
```bash
sudo systemctl status hostapd
```

4. Manually set wlan0 to AP mode:
```bash
sudo ip link set wlan0 down
sudo iw dev wlan0 set type __ap
sudo ip link set wlan0 up
sudo systemctl restart hostapd
```

### If the web page doesn't load:

1. Check if Nginx is running:
```bash
sudo systemctl status nginx
```

2. Check Nginx error logs:
```bash
sudo tail -n 50 /var/log/nginx/error.log
```

3. Verify file permissions:
```bash
sudo chmod -R 755 "/home/olivier/Documents/AI powered company/meeting-notes/meeting-assistant"
```

4. Ensure the service dependencies are correct:
```bash
sudo systemctl list-dependencies nginx-after-ap.service
```

### If you need to modify the web content:

Simply edit the files in the meeting-assistant directory and the changes will be immediately available when you refresh the browser.

## Accessing the Web Page

To access your web page from any device connected to the Raspberry Pi's access point:

1. Connect to the "meeting-assistant" Wi-Fi network (using the password you configured)
2. Open a web browser
3. Navigate to: `http://192.168.4.1`

This is the IP address of your Raspberry Pi on the access point network, as configured in your access point setup.

## Additional Notes

1. This setup serves static files only. If you need to run server-side code (PHP, Python, etc.), additional configuration will be needed.
2. The web server is only accessible from devices connected to the Raspberry Pi's access point.
3. For security, this setup doesn't include HTTPS, as it's a local-only service without internet connectivity.
4. If you move the location of your HTML files, you'll need to update the Nginx configuration accordingly.