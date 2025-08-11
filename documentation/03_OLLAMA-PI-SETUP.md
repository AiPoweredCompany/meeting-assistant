## Raspberry Pi: Ollama + Meeting Summarizer Setup

This guide sets up Ollama to start at boot on your Raspberry Pi and adds a small Python backend that accepts a `.txt` transcript, builds the required prompt, calls Ollama, and returns a summary. The existing `index.html` button “Ouvrir” will upload the file and display the summary in a new tab.

### Overview
- Ollama API runs on `127.0.0.1:11434` and serves models (e.g. `mistral:latest`).
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
ollama pull mistral:latest
```

Quick test:
```
curl -X POST http://127.0.0.1:11434/api/generate -d '{
  "model": "mistral:latest",
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

- If it exists (installed by Ollama script on some systems):
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
# Optional: place model store on SSD/NVMe to reduce SD wear (ensure path exists & is writable)
# Environment=OLLAMA_MODELS=/mnt/ssd/ollama

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

Verify on reboot:
```
sudo reboot
# after reconnecting
systemctl status ollama --no-pager
ss -ltnp | grep 11434 || true
journalctl -u ollama -b -n 50 --no-pager
```

Optional: expose Ollama API on your LAN (only if you understand the security implications). Change in the service:
```
Environment=OLLAMA_HOST=0.0.0.0:11434
```
Then reload and restart:
```
sudo systemctl daemon-reload && sudo systemctl restart ollama
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
Environment="PYTHONUNBUFFERED=1" \
           "OLLAMA_URL=http://127.0.0.1:11434" \
           "OLLAMA_MODEL=mistral:latest" \
           "OLLAMA_TIMEOUT_SECONDS=3600"   # increase backend wait time (optional) \
           "DEBUG_SUMMARIZER=0"            # set to 1 to include debug metadata in responses (optional)
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
- The backend exposes `POST /summarize` expecting form-data: `file=@...` (required, `.txt`), plus optional:
  - `model` (override default model)
  - `timeout_seconds` (per-request wait time)
  - `num_predict` (max tokens to generate)
  - `num_ctx` (context window tokens, model-dependent)
  - `temperature` (sampling temperature)
  - `debug=1` (include debug metadata and prompt head in JSON)
  - `use_chat=1` (use chat endpoint with system/user split to reduce instruction echo)

---

### 4) Frontend wiring
The file `meeting-assistant/index.html` is wired so that clicking the “Ouvrir” button:
- Ensures the selected file is a `.txt`.
- Uploads it as `multipart/form-data` to `http://127.0.0.1:8000/summarize`.
- Opens a new tab with the summary returned by the backend.

Optional: you can override generation via query string when opening the page (the page forwards these to the backend):
```
index.html?model=mistral:latest&timeout_seconds=3600&num_predict=512&num_ctx=8192&temperature=0.2&use_chat=1&debug=0
```
Supported params forwarded to the backend:
- `model` (e.g., `mistral:latest`)
- `timeout_seconds` (seconds to wait for Ollama)
- `num_predict` (max tokens to generate)
- `num_ctx` (context window tokens; must be supported by the model)
- `temperature` (sampling temperature)
- `use_chat` (set `1` to use chat formatting; can reduce prompt/template echo)
- `debug` (set `1` to include debug metadata in JSON response)

---

### 5) Prompt structure used by the backend
- The backend reads the entire `.txt` into a variable `transcription_body`.
- It builds `prompt` by inserting `transcription_body` at the placeholder `<TEXT TO ADD HERE>` in your multi-language, structured summary instructions.
- It calls `POST /api/generate` on Ollama with `{"model": ..., "prompt": ..., "stream": false}`.

Tip: To further reduce the model echoing the instructions, the backend also supports chat mode (`use_chat=1`) which sends the instructions as `system` and the transcript as `user`.

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

Optional warm-up (first run can be slow while the model loads/compiles):
```
curl -sS -X POST http://127.0.0.1:11434/api/generate -d '{"model":"mistral:latest","prompt":"hi","stream":false}' | cat
```

Manual cURL testing examples:
```
# Long timeout & shorter output to finish faster
curl -sS -F "file=@tests/false_transcription.txt" \
     -F "timeout_seconds=3600" -F "num_predict=512" \
     http://127.0.0.1:8000/summarize | jq -r .summary

# Enable chat mode to reduce template echo
curl -sS -F "file=@tests/false_transcription.txt" \
     -F "use_chat=1" \
     http://127.0.0.1:8000/summarize | jq -r .summary

# Inspect prompt head and metadata (debug)
curl -sS -F "file=@tests/false_transcription.txt" -F "debug=1" \
     http://127.0.0.1:8000/summarize | jq .
```

---

### 7) Troubleshooting
- Port in use / multiple Ollama instances:
  - `ss -ltnp | grep 11434`
  - Stop local foreground runs and use the systemd service only.
- Model not found / slow start:
  - `ollama pull mistral:latest`
  - First run compiles; subsequent runs are faster.
- Backend errors:
  - Logs: `journalctl -u meeting-summarizer -e -n 200`
  - Health: `curl -f http://127.0.0.1:8000/healthz`
- Request timeouts:
  - Increase `timeout_seconds` per request or set `OLLAMA_TIMEOUT_SECONDS=3600` in the service.
  - Reduce `num_predict` (e.g., 256–512) and/or transcript length.
  - Use warm-up call before long requests.
- Memory pressure on Pi:
  - Increase swap (dphys-swapfile) if OOM occurs with 7B models.

---

### Maintenance
- Update Ollama: re-run the install script or package manager as appropriate.
- Change default model: edit env `OLLAMA_MODEL` in `meeting-summarizer` unit, then `sudo systemctl daemon-reload && sudo systemctl restart meeting-summarizer`.
- Upgrade Python deps: `"$ROOT/env/bin/pip" install -U -r "$ROOT/meeting-assistant/requirements.txt"`

---

### Questions
- Do you want a different default model than `mistral:latest`?
- Should the backend listen on another interface/port (e.g., accessible from other devices)?

