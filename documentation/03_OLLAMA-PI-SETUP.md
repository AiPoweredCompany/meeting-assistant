## Raspberry Pi: Ollama + Meeting Summarizer Setup

This guide sets up Ollama to start at boot on your Raspberry Pi and adds a small Python backend that accepts a `.txt` transcript, builds the required prompt, calls Ollama, and returns a summary. The existing `index.html` button “Ouvrir” will upload the file and display the summary in a new tab.

### Overview
- Ollama API runs on `127.0.0.1:11434` and serves models (e.g. `yarn-mistral:7b-128k`).
- A Flask backend listens on `127.0.0.1:8000` at `POST /summarize` and calls Ollama.
- The web page `meeting-assistant/index.html` sends the selected `.txt` transcript to the backend and opens the generated summary.

---

### 0) Prerequisites
- Raspberry Pi 5 recommended (Pi 4 can work with more swap).
- 64-bit Raspberry Pi OS.
- Ensure swap size is reasonably large (4–8 GB) if running a 7B model entirely on CPU.
- Confirm the repo path (adjust if different):
  - `ROOT=/home/olivier/Documents/AI powered company/meeting-notes`

---

### 0.1) Configure swap size (Raspberry Pi OS)
If you run 7B models on CPU, increase swap to avoid out-of-memory kills.

- Check current swap:
```
free -h
swapon --show
```

- Install the swap manager (if not present):
```
sudo apt update && sudo apt install -y dphys-swapfile
```

- Disable current swap and stop the service before changes:
```
sudo dphys-swapfile swapoff
sudo systemctl stop dphys-swapfile
```

- Edit the config file:
```
sudo nano /etc/dphys-swapfile
```
Set one of the following values (uncomment or add the lines):
```
CONF_SWAPSIZE=4096   # 4 GB (safe starting point)
# Or for more headroom (uses more disk space):
# CONF_SWAPSIZE=8192  # 8 GB

# Important: raise the default max swap cap (default is 2048 MB)
CONF_MAXSWAP=16384   # allow up to 16 GB; you can set 8192 if you prefer
```

Optional: move swap to SSD/NVMe to reduce SD card wear (ensure the mount exists and has space):
```
CONF_SWAPFILE=/mnt/ssd/swapfile
```

- Apply and re-enable swap:
```
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
sudo systemctl enable --now dphys-swapfile
```

If you see a message like "restricting to config limit: 2048MBytes", you forgot to raise `CONF_MAXSWAP`. Edit `/etc/dphys-swapfile` to add `CONF_MAXSWAP=8192` (or larger), then rerun the three commands above.

- Verify:
```
swapon --show
free -h
```

Notes and recommendations:
- 4 GB typically works for 7B CPU inference; 8 GB gives more headroom.
- Prefer placing swap on SSD/NVMe over SD cards to reduce wear.
- Alternative (reduced disk wear): zram compressed RAM swap.
  - Install: `sudo apt install -y zram-tools`
  - Optionally tune `/etc/default/zramswap`, then enable: `sudo systemctl enable --now zramswap`
  - You can combine zram with a modest disk-backed swap for best stability.

---

### 1) Install Ollama (if not already installed)
```
curl -fsSL https://ollama.com/install.sh | sh
```
Verify:
```
which ollama
ollama --version
```

Pull your model (example):
```
ollama pull yarn-mistral:7b-128k
```

Quick test:
```
curl -X POST http://127.0.0.1:11434/api/generate -d '{
  "model": "yarn-mistral:7b-128k",
  "prompt": "Here is a story about llamas eating grass"
}'
```

If `127.0.0.1:11434` is listening, Ollama is running:
```
ss -ltnp | grep 11434 || true
```

---

### 2) Run Ollama on boot (systemd)
First check if a service exists already:
```
systemctl status ollama --no-pager || true
```

- If it exists:
```
sudo systemctl enable --now ollama
```

- If not present, create `/etc/systemd/system/ollama.service`:
```
sudo tee /etc/systemd/system/ollama.service >/dev/null <<'UNIT'
[Unit]
Description=Ollama Server
After=network-online.target
Wants=network-online.target

[Service]
User=olivier
Group=olivier
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=2
Environment=OLLAMA_HOST=127.0.0.1:11434

[Install]
WantedBy=multi-user.target
UNIT
```
Adjust `ExecStart` if `which ollama` shows a different path.

Enable and start:
```
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
systemctl status ollama --no-pager
```

---

### 3) Python backend (Flask) to call Ollama
Files (already added):
- `meeting-assistant/summarize_server.py`
- `meeting-assistant/requirements.txt`

Install dependencies into your existing venv:
```
"$ROOT/env/bin/pip" install -r "$ROOT/meeting-assistant/requirements.txt"
```

Manual run (for test):
```
"$ROOT/env/bin/python" "$ROOT/meeting-assistant/summarize_server.py"
# health check
curl -f http://127.0.0.1:8000/healthz
# test summarize
curl -F "file=@/path/to/transcript.txt" http://127.0.0.1:8000/summarize | jq -r .summary
```

Service on boot (systemd): create `/etc/systemd/system/meeting-summarizer.service`:
```
sudo tee /etc/systemd/system/meeting-summarizer.service >/dev/null <<'UNIT'
[Unit]
Description=Meeting Summarizer backend (Flask)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=olivier
Group=olivier
Environment="PYTHONUNBUFFERED=1" "OLLAMA_URL=http://127.0.0.1:11434" "OLLAMA_MODEL=yarn-mistral:7b-128k"
ExecStart="/home/olivier/Documents/AI powered company/meeting-notes/env/bin/python" \
         "/home/olivier/Documents/AI powered company/meeting-notes/meeting-assistant/summarize_server.py"
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
```

Enable and start:
```
sudo systemctl daemon-reload
sudo systemctl enable --now meeting-summarizer
systemctl status meeting-summarizer --no-pager
```

Notes:
- Paths contain spaces. Keep the quotes in `ExecStart` exactly.
- The backend exposes `POST /summarize` expecting form-data `file=@...` with a `.txt`, and optional `model=...` to override the default model.

---

### 4) Frontend wiring
The file `meeting-assistant/index.html` is wired so that clicking the “Ouvrir” button:
- Ensures the selected file is a `.txt`.
- Uploads it as `multipart/form-data` to `http://127.0.0.1:8000/summarize`.
- Opens a new tab with the summary returned by the backend.

Optional: you can override the model via query string, e.g. open the page as:
```
index.html?model=llama3:8b
```

---

### 5) Prompt structure used by the backend
- The backend reads the entire `.txt` into a variable `transcription_body`.
- It builds `prompt` by inserting `transcription_body` at the placeholder `<TEXT TO ADD HERE>` in your multi-language, structured summary instructions.
- It calls `POST /api/generate` on Ollama with `{"model": ..., "prompt": ..., "stream": false}`.

---

### 6) End-to-end test
1) Confirm Ollama is listening:
```
ss -ltnp | grep 11434 || true
```
2) Confirm backend is ready:
```
curl -f http://127.0.0.1:8000/healthz
```
3) Open `meeting-assistant/index.html` in a browser on the Pi.
4) Click “Ouvrir”, select a `.txt` transcript, wait for generation, and a new tab should display the summary.

---

### 7) Troubleshooting
- Port in use / multiple Ollama instances:
  - `ss -ltnp | grep 11434`
  - Stop local foreground runs and use the systemd service only.
- Model not found / slow start:
  - `ollama pull yarn-mistral:7b-128k`
  - First run compiles; subsequent runs are faster.
- Backend errors:
  - Logs: `journalctl -u meeting-summarizer -e -n 200`
  - Health: `curl -f http://127.0.0.1:8000/healthz`
- Memory pressure on Pi:
  - Increase swap (dphys-swapfile) if OOM occurs with 7B models.

---

### Maintenance
- Update Ollama: re-run the install script or package manager as appropriate.
- Change default model: edit env `OLLAMA_MODEL` in `meeting-summarizer` unit, then `sudo systemctl daemon-reload && sudo systemctl restart meeting-summarizer`.
- Upgrade Python deps: `"$ROOT/env/bin/pip" install -U -r "$ROOT/meeting-assistant/requirements.txt"`

---

### Questions
- Do you want a different default model than `yarn-mistral:7b-128k`?
- Should the backend listen on another interface/port (e.g., accessible from other devices)?

