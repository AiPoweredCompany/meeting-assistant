import subprocess
import threading
import queue
import sounddevice as sd
import numpy as np
import wave
import time
import os
import whisper
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from datetime import datetime
from typing import Dict, List, Optional

app = Flask(__name__)
CORS(app)

# Global variables pour stocker l’état
capture_threads = []
worker_thread = None
transcription_results = []
# Deux événements séparés pour éviter les arrêts intempestifs
capture_stop_event = threading.Event()      # arrête la capture
worker_stop_event = threading.Event()       # arrête le worker quand la file est vide

# Mapping mic_id -> person_name pour affichage
mic_id_to_person = {}

# Dernier chemin de transcription sauvegardé
auto_saved_transcription_path = None

# Preview levels (VU-meter) state
preview_threads: Dict[int, threading.Thread] = {}
preview_stop_event = threading.Event()
mic_levels: Dict[int, float] = {}
mic_levels_lock = threading.Lock()

# Queue pour communication entre thread capture et transcription
audio_queue = queue.Queue()

# Chargement modèle Whisper une fois au démarrage
model = whisper.load_model("base")

# Fonction pour détecter les micros via PortAudio/sounddevice
# Retourne une liste de dicts: {mic_id, device_index, name, default_samplerate}
def detect_mics():
    devices = sd.query_devices()
    inputs = []
    for idx, d in enumerate(devices):
        try:
            max_in = d.get('max_input_channels', 0)
        except Exception:
            max_in = 0
        if max_in and max_in > 0:
            inputs.append({
                "device_index": idx,
                "name": d.get('name', f'device-{idx}'),
                "default_samplerate": d.get('default_samplerate', None)
            })
    # Attribuer des mic_id 1..N pour l'UI
    data = []
    for i, info in enumerate(inputs, start=1):
        data.append({
            "mic_id": i,
            "device_index": info["device_index"],
            "name": info["name"],
            "default_samplerate": info["default_samplerate"],
        })
    return data

# Santé du serveur
@app.route('/healthz', methods=['GET'])
def api_healthz():
    try:
        _ = model  # ensure loaded
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# Choisit un taux d'échantillonnage supporté par ce device
def choose_supported_samplerate(device_index: int) -> int:
    preferred = [16000, 48000, 44100, 32000, 22050, 8000]
    for sr in preferred:
        try:
            sd.check_input_settings(device=device_index, samplerate=sr, channels=1)
            return sr
        except Exception:
            continue
    # fallback: utiliser le samplerate par défaut du device
    try:
        d = sd.query_devices(device_index)
        dsr = int(d.get('default_samplerate', 16000))
        sd.check_input_settings(device=device_index, samplerate=dsr, channels=1)
        return dsr
    except Exception:
        return 16000

# Thread de preview niveau pour un device donné
def _preview_level_worker(device_index: int, mic_id: int):
    fs = choose_supported_samplerate(device_index)
    blocksize = 1024
    dtype = 'int16'
    try:
        with sd.InputStream(device=device_index, channels=1, samplerate=fs, blocksize=blocksize, dtype=dtype) as stream:
            while not preview_stop_event.is_set():
                data, _ = stream.read(blocksize)
                if data is None:
                    continue
                # Calcul RMS normalisé 0..1
                arr = data.astype('float32') / 32768.0
                rms = float(np.sqrt(np.mean(arr ** 2)))
                with mic_levels_lock:
                    mic_levels[mic_id] = rms
    except Exception as e:
        with mic_levels_lock:
            mic_levels[mic_id] = -1.0

@app.route('/start_mic_test', methods=['POST'])
def api_start_mic_test():
    global preview_threads
    # empêcher conflit avec capture
    if capture_threads:
        return jsonify({"status": "error", "message": "Transcription en cours"}), 400
    content = request.json or {}
    requested_ids: Optional[List[int]] = content.get('mic_ids')
    mics = detect_mics()
    mic_map = {m['mic_id']: m['device_index'] for m in mics}

    preview_stop_event.clear()
    with mic_levels_lock:
        mic_levels.clear()
    preview_threads = {}

    ids = requested_ids if requested_ids else list(mic_map.keys())
    for mic_id in ids:
        if mic_id not in mic_map:
            continue
        device_index = mic_map[mic_id]
        t = threading.Thread(target=_preview_level_worker, args=(device_index, mic_id), daemon=True)
        t.start()
        preview_threads[mic_id] = t
    return jsonify({"status": "started", "mic_ids": ids})

@app.route('/mic_levels', methods=['GET'])
def api_mic_levels():
    with mic_levels_lock:
        levels = dict(mic_levels)
    return jsonify({"levels": levels})

@app.route('/stop_mic_test', methods=['POST'])
def api_stop_mic_test():
    preview_stop_event.set()
    for t in list(preview_threads.values()):
        try:
            t.join(timeout=1)
        except Exception:
            pass
    preview_threads.clear()
    return jsonify({"status": "stopped"})

# Fonction pour enregistrer par segments avec horodatage et placer dans queue
def record_segments(device_index, mic_id, segment_duration=30, chunk_duration=2):
    # Choisir un SR supporté par le device
    fs = choose_supported_samplerate(device_index)
    print(f"[{mic_id}] Démarrage capture segmentée sur device #{device_index} @ {fs} Hz")

    # Accumulateur pour constituer un segment à partir de petits morceaux
    chunks = []
    collected_samples = 0
    samples_per_segment = int(segment_duration * fs)
    samples_per_chunk = max(1, int(chunk_duration * fs))

    while not capture_stop_event.is_set():
        try:
            # Enregistrer un petit morceau afin de pouvoir s'arrêter rapidement
            small = sd.rec(samples_per_chunk, samplerate=fs, channels=1, dtype='int16', device=device_index)
            sd.wait()
            chunks.append(small)
            collected_samples += len(small)

            if collected_samples >= samples_per_segment:
                # Écrire le segment et l'envoyer à la transcription
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
                filename = f"audio_{mic_id}_{timestamp}.wav"
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(fs)
                    wf.writeframes(np.concatenate(chunks, axis=0).tobytes())
                print(f"[{mic_id}] Segment enregistré : {filename}")
                audio_queue.put((mic_id, filename, timestamp))
                # Reset accumulateur pour le prochain segment
                chunks = []
                collected_samples = 0
        except Exception as e:
            print(f"[{mic_id}] Erreur enregistrement : {e}")
            break

    # Si on arrête et qu'il reste des données partielles, on les flush en dernier segment
    if collected_samples > 0 and len(chunks) > 0:
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"audio_{mic_id}_{timestamp}.wav"
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(fs)
                wf.writeframes(np.concatenate(chunks, axis=0).tobytes())
            print(f"[{mic_id}] Segment partiel enregistré (arrêt): {filename}")
            audio_queue.put((mic_id, filename, timestamp))
        except Exception as e:
            print(f"[{mic_id}] Échec flush segment partiel: {e}")

    print(f"[{mic_id}] Fin capture")

# Thread transcription : récupère fichiers depuis queue, transcrit, stocke résultats
def transcription_worker():
    while not worker_stop_event.is_set() or not audio_queue.empty():
        try:
            mic_id, filename, timestamp = audio_queue.get(timeout=1)
        except queue.Empty:
            continue
        print(f"[Transcription] Traitement {filename} (Micro {mic_id})")
        try:
            result = model.transcribe(filename, language=None)  # Auto détection
            text = result['text'].strip()
            # Stocker dans global (thread safe ? ici simplifié)
            transcription_results.append({
                "mic_id": mic_id,
                "person_name": mic_id_to_person.get(mic_id),
                "timestamp": timestamp,
                "text": text
            })
            print(f"[Transcription] Texte {mic_id} @ {timestamp}: {text}")
        except Exception as e:
            print(f"[Transcription] Erreur transcription {filename}: {e}")
        finally:
            # Supprimer fichier audio après transcription pour économiser place
            if os.path.exists(filename):
                os.remove(filename)
        audio_queue.task_done()
    print("[Transcription] Thread terminé")

# Endpoint API Flask

@app.route('/detect_mics', methods=['GET'])
def api_detect_mics():
    mics = detect_mics()
    return jsonify({"mics": mics})

@app.route('/start_transcription', methods=['POST'])
def api_start_transcription():
    global capture_threads, worker_thread, transcription_results, mic_id_to_person, auto_saved_transcription_path
    if capture_threads or worker_thread:
        return jsonify({"status": "error", "message": "Transcription déjà en cours"}), 400

    content = request.json
    # Exemple de payload attendu : { "assignments": [{"mic_id":1, "person_name":"Alice"}, ...]}
    assignments = content.get("assignments", [])
    if not assignments:
        return jsonify({"status": "error", "message": "Pas d'assignation fournie"}), 400

    capture_stop_event.clear()
    worker_stop_event.clear()
    transcription_results.clear()
    auto_saved_transcription_path = None
    capture_threads = []
    worker_thread = None

    # Détecter micros disponibles (PortAudio)
    mics = detect_mics()
    mic_map = {m['mic_id']: m['device_index'] for m in mics}

    # Enregistrer les noms de personnes et lancer capture segmentée
    mic_id_to_person = {a['mic_id']: a.get('person_name') for a in assignments if a.get('mic_id')}
    for a in assignments:
        mic_id = a['mic_id']
        if mic_id not in mic_map:
            return jsonify({"status": "error", "message": f"Mic ID {mic_id} non détecté"}), 400
        device_index = mic_map[mic_id]
        t = threading.Thread(target=record_segments, args=(device_index, mic_id), kwargs={"segment_duration": 15, "chunk_duration": 2}, daemon=True)
        t.start()
        capture_threads.append(t)

    # Lancer thread transcription
    worker_thread = threading.Thread(target=transcription_worker, daemon=True)
    worker_thread.start()

    return jsonify({"status": "started", "message": f"Transcription démarrée pour {len(assignments)} micros"})

@app.route('/stop_transcription', methods=['POST'])
def api_stop_transcription():
    global capture_threads, worker_thread, auto_saved_transcription_path
    # Arrêter la capture d'abord
    capture_stop_event.set()
    for t in capture_threads:
        try:
            t.join(timeout=2)
        except Exception:
            pass
    capture_threads.clear()

    # Attendre la fin du traitement de la file, puis arrêter le worker
    try:
        audio_queue.join()
    except Exception:
        pass
    worker_stop_event.set()
    if worker_thread:
        try:
            worker_thread.join(timeout=2)
        except Exception:
            pass
        worker_thread = None

    # Auto-save transcription and return path
    auto_saved_transcription_path = _save_full_transcription()

    return jsonify({"status": "stopped", "file_path": auto_saved_transcription_path})

@app.route('/get_transcriptions', methods=['GET'])
def api_get_transcriptions():
    # Fusionner les résultats par timestamp global
    sorted_transcripts = sorted(transcription_results, key=lambda x: x['timestamp'])
    # Formatage texte fusionné
    full_text = ""
    for tr in sorted_transcripts:
        dt = datetime.strptime(tr['timestamp'], "%Y%m%d_%H%M%S_%f")
        timestamp_str = dt.strftime("%H:%M:%S")
        label = tr.get('person_name') or f"Micro {tr['mic_id']}"
        full_text += f"[{timestamp_str}] {label}: {tr['text']}\n"
    return jsonify({"transcription": full_text})

def _save_full_transcription() -> str:
    sorted_transcripts = sorted(transcription_results, key=lambda x: x['timestamp'])
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"full_transcription_{ts}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        for tr in sorted_transcripts:
            dt = datetime.strptime(tr['timestamp'], "%Y%m%d_%H%M%S_%f")
            timestamp_str = dt.strftime("%H:%M:%S")
            label = tr.get('person_name') or f"Micro {tr['mic_id']}"
            f.write(f"[{timestamp_str}] {label}: {tr['text']}\n")
    return os.path.abspath(filename)

@app.route('/download_transcription', methods=['GET'])
def api_download_transcription():
    path = _save_full_transcription()
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
