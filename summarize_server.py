import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "3600"))  # 60 minutes


PROMPT_TEMPLATE = """ You are an expert summarizer specialized in professional IT interviews between clients and providers, particularly around product development and workflow optimization. Your task is to:

1. Automatically detect the languages in the interview transcript (English, Spanish, French). The text may contain multiple languages mixed.

2. For each detected language section, create a separate summary section written in that language.

3. The summary must be clear, concise, and well organized into the following categories:

   - Client Needs and Goals  
   - Technical Challenges and Constraints  
   - Proposed Solutions and Recommendations  
   - Decisions and Agreements  
   - Action Items and Next Steps  
   - Additional Notes (if any)

4. Use paraphrased content, avoid direct quotes unless absolutely necessary for clarity.

5. Make sure to capture any important action items or follow-up tasks explicitly, as these are critical.

6. Follow the structure below exactly, replicating the formatting and style:

---

**Summary of Interview**

### Section: [Language Name]

- **Client Needs and Goals:**  
  [Paraphrased summary of client’s objectives and expectations in this language.]

- **Technical Challenges and Constraints:**  
  [Paraphrased description of technical difficulties or limitations mentioned.]

- **Proposed Solutions and Recommendations:**  
  [Summary of suggested approaches, tools, or methods discussed.]

- **Decisions and Agreements:**  
  [Summary of key decisions or mutual agreements reached.]

- **Action Items and Next Steps:**  
  [Clear list of tasks or follow-ups decided during the interview.]

- **Additional Notes:**  
  [Any other relevant remarks.]

---

Output rules: Only produce the "Summary of Interview" section(s) as specified above. Do not repeat any of the instructions or template text in your answer. Do not include the label "Input Transcript" in the output.

Input Transcript:  

<TEXT TO ADD HERE>

Please provide the summary now.

 """


def build_prompt_from_transcript(transcription_body: str) -> str:
    return PROMPT_TEMPLATE.replace("<TEXT TO ADD HERE>", transcription_body)


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/summarize")
    def summarize():
        if "file" not in request.files:
            return jsonify({"error": "Missing file in form-data with key 'file'"}), 400

        uploaded_file = request.files["file"]
        filename = (uploaded_file.filename or "").lower()
        if not filename.endswith(".txt"):
            return jsonify({"error": "Only .txt files are supported"}), 400

        try:
            content_bytes = uploaded_file.read()
            transcription_body = content_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            return jsonify({"error": "Failed to read file", "detail": str(exc)}), 400

        prompt = build_prompt_from_transcript(transcription_body)

        model = request.form.get("model", DEFAULT_MODEL)

        # Optional generation options
        options: dict = {}
        def parse_int_field(name: str) -> int | None:
            value = request.form.get(name)
            if value is None:
                return None
            try:
                return int(value)
            except ValueError:
                return None

        num_ctx = parse_int_field("num_ctx")
        if num_ctx is not None:
            options["num_ctx"] = num_ctx

        num_predict = parse_int_field("num_predict")
        if num_predict is not None:
            options["num_predict"] = num_predict

        temperature = request.form.get("temperature")
        if temperature is not None:
            try:
                options["temperature"] = float(temperature)
            except ValueError:
                pass

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            payload["options"] = options

        try:
            # Optional debug info and chat mode
            debug_enabled = request.form.get("debug") in ("1", "true", "yes") or os.getenv("DEBUG_SUMMARIZER") in ("1", "true", "yes")
            use_chat = request.form.get("use_chat") in ("1", "true", "yes")

            # Allow per-request override of timeout_seconds, else use default
            timeout_override = parse_int_field("timeout_seconds")
            effective_timeout = timeout_override if timeout_override and timeout_override > 0 else DEFAULT_TIMEOUT_SECONDS
            used_endpoint = "generate"

            if use_chat:
                # Convert to chat format: system = instructions/template, user = transcript
                used_endpoint = "chat"
                chat_payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": PROMPT_TEMPLATE.replace("Input Transcript:  \n\n<TEXT TO ADD HERE>\n\nPlease provide the summary now.\n\n ", "").strip()},
                        {"role": "user", "content": f"Transcript (do not repeat):\n\n{transcription_body}\n\nPlease provide the structured summary now following the template."},
                    ],
                    "stream": False,
                }
                if options:
                    chat_payload["options"] = options
                resp = requests.post(f"{OLLAMA_URL}/api/chat", json=chat_payload, timeout=effective_timeout)
                resp.raise_for_status()
                data = resp.json()
                message = data.get("message", {})
                summary_text = message.get("content", "")
            else:
                resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=effective_timeout)
                resp.raise_for_status()
                data = resp.json()
                summary_text = data.get("response", "")

            if debug_enabled:
                logging.info("Model: %s | Endpoint: %s | Timeout: %s | Options: %s", model, used_endpoint, effective_timeout, options or {})
                logging.info("Prompt length: %d | Head: %r", len(prompt), prompt[:400])
                # Return debug metadata in response (trim head to avoid huge payloads)
                return jsonify({
                    "summary": summary_text,
                    "debug": {
                        "model": model,
                        "endpoint": used_endpoint,
                        "timeout_seconds": effective_timeout,
                        "options": options or {},
                        "prompt_length": len(prompt),
                        "prompt_head": prompt[:1000],
                    }
                })

            return jsonify({"summary": summary_text})
        except requests.RequestException as exc:
            return (
                jsonify({
                    "error": "Ollama request failed",
                    "detail": str(exc),
                    "ollama_url": OLLAMA_URL,
                    "model": model,
                }),
                502,
            )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

