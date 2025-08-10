## Meeting Assistant Page Slow/Not Working Over AP — Diagnose & Fix (Raspberry Pi 5)

This guide helps you find and fix why `index.html` is slow or features don't work when served from your Raspberry Pi 5 access point. Your Pi has no internet access, so any external resources or services will fail and can cause slow loads/timeouts.

### Root causes to check first (most likely)
- External scripts or calls (CDNs, APIs) are blocked offline
- Wi‑Fi AP configured for legacy speeds (802.11g only, WMM off)
- Nginx not optimized (minor) or reading from a slow/blocked path

Your `index.html` currently loads EmailJS from the internet:
```
<script src="https://cdn.jsdelivr.net/npm/@emailjs/browser@3/dist/email.min.js"></script>
```
This will block/fail on a standalone AP (no internet) and make the page feel slow/unresponsive. Email sending also won’t work offline.

---

### Part A — Verify the current server and file path

- Confirm web root and index location (adjust WEB_ROOT if different):
```bash
WEB_ROOT="/home/olivier/meeting-assistant"
ls -la "$WEB_ROOT/index.html"
```
- Verify Nginx is using your intended root:
```bash
sudo grep -n "root " /etc/nginx/sites-available/default
sudo nginx -t
```
- Quick timing from the Pi:
```bash
curl -s -o /dev/null -w 'TTFB: %{time_starttransfer}s  Total: %{time_total}s\n' http://localhost/
```
- Tail logs while loading the page from your phone:
```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

Expected: 200 for `/` with small times. If you see repeated 404/timeout lines for external domains, your page is trying to reach the internet.

---

### Part B — Make the page fully offline (no external CDN/API)

Option 1 — Remove EmailJS usage (simplest, fully offline)
- Edit `index.html` and remove the external EmailJS `<script>` and all calls to `emailjs.init(...)` and `emailjs.send(...)`.
- Replace email send button behavior with a local no‑op message:
```html
<!-- Replace EmailJS script tag with nothing (remove it) -->
<!-- Remove any emailjs.init(...) call -->
<script>
  // Disable email sending when offline
  document.addEventListener('DOMContentLoaded', () => {
    const submitBtn = document.querySelector('.submit-btn');
    if (submitBtn) {
      submitBtn.addEventListener('click', () => {
        alert('Email sending is disabled in offline mode.');
      });
    }
  });
</script>
```

Option 2 — Host the EmailJS browser SDK locally (still, sending emails won’t work offline)
- On your laptop (with internet):
```bash
curl -L -o email.min.js "https://cdn.jsdelivr.net/npm/@emailjs/browser@3/dist/email.min.js"
```
- Copy it to the Pi (connected to the AP). Adjust user/host/path as needed:
```bash
scp email.min.js olivier@192.168.4.1:"$WEB_ROOT/"
```
- Update `index.html` to use the local file and guard when offline:
```html
<!-- Replace the CDN tag with the local file -->
<script src="/email.min.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', () => {
    const submitBtn = document.querySelector('.submit-btn');

    const emailJsAvailable = (typeof window.emailjs !== 'undefined');
    if (!emailJsAvailable) {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.title = 'Email sending unavailable in offline mode';
      }
      return;
    }

    // Initialize only if available
    emailjs.init('YOUR_PUBLIC_KEY');

    if (submitBtn) {
      submitBtn.addEventListener('click', async () => {
        alert('This Pi is offline. Email sending will fail in this environment.');
      });
    }
  });
</script>
```
- Reload Nginx:
```bash
sudo systemctl restart nginx
```

---

### Part C — Improve Wi‑Fi AP throughput

Your current hostapd config disables 802.11n and WMM. Re‑enable them for much better speed.

1) Edit hostapd config:
```bash
sudo nano /etc/hostapd/hostapd.conf
```
Change/add:
```
# 2.4 GHz, enable 802.11n + WMM
hw_mode=g
channel=1
ieee80211n=1
wmm_enabled=1
ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40]
```
Optional 5 GHz (if your Pi 5 Wi‑Fi and clients support it):
```
hw_mode=a
channel=36
ieee80211n=1
ieee80211ac=1
wmm_enabled=1
vht_capab=[SHORT-GI-80]
```
Note: Only one band config (2.4 or 5 GHz) should be active at a time in this simple setup.

2) Reduce hostapd verbosity (avoid -dd in service):
```bash
sudo nano /etc/systemd/system/hostapd-custom.service
```
Change:
```
ExecStart=/usr/sbin/hostapd -dd /etc/hostapd/hostapd.conf
```
To:
```
ExecStart=/usr/sbin/hostapd /etc/hostapd/hostapd.conf
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart hostapd-custom.service
```

3) Verify AP mode and capabilities:
```bash
iw dev wlan0 info
sudo iw dev wlan0 station dump  # shows per‑client tx/rx bitrate
```
Look for higher data rates after enabling 802.11n/WMM.

---

### Part D — Light Nginx tuning (optional)

1) Enable gzip, sendfile, modest caching of static assets:
```bash
sudo nano /etc/nginx/nginx.conf
```
Inside the `http { ... }` block, ensure/add:
```
sendfile on;
tcp_nopush on;
tcp_nodelay on;

gzip on;
gzip_disable "msie6";
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_buffers 16 8k;
gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
```
2) Cache headers for static files:
```bash
sudo nano /etc/nginx/sites-available/default
```
In your `server { ... }` block add:
```
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
  expires 30d;
  add_header Cache-Control "public, no-transform";
}
```
Apply:
```bash
sudo nginx -t && sudo systemctl restart nginx
```

---

### Part E — Validation checklist

- From the Pi:
```bash
curl -s -o /dev/null -w 'TTFB: %{time_starttransfer}s  Total: %{time_total}s\n' http://localhost/
```
- From your phone (connected to the AP), reload the page after clearing cache
- Check logs while loading from the phone:
```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```
- Confirm no requests to external CDNs/APIs appear in the browser’s network panel
- Check Wi‑Fi bitrate seen by the AP:
```bash
sudo iw dev wlan0 station dump | grep -E "Station|bitrate"
```

---

### What to expect after fixes
- Page loads quickly and consistently (sub‑second TTFB locally)
- No stalled requests to external CDNs
- Email sending is disabled or clearly messaged as unavailable offline
- Higher Wi‑Fi link rates after enabling 802.11n/WMM (and 5 GHz if used)

### If issues persist, please tell me:
- Your current `WEB_ROOT` path
- The full `/etc/hostapd/hostapd.conf`
- Output of:
```bash
iw dev wlan0 info
sudo iw dev wlan0 station dump
curl -s -o /dev/null -w 'TTFB: %{time_starttransfer}s  Total: %{time_total}s\n' http://localhost/
```
