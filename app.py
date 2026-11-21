import io
import os
import uuid
from collections import OrderedDict

from flask import Flask, jsonify, render_template, request

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

import llm  # noqa: E402  (after load_dotenv so env vars are visible)

# Static files live in public/static so Vercel serves them from its CDN
app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB uploads

# Keep the last few uploaded documents in memory so /api/ask and /api/plan
# do not need the browser to send the whole text again.
DOCS: "OrderedDict[str, str]" = OrderedDict()
MAX_DOCS = 20


def remember(text: str) -> str:
    doc_id = uuid.uuid4().hex[:12]
    DOCS[doc_id] = text
    while len(DOCS) > MAX_DOCS:
        DOCS.popitem(last=False)
    return doc_id


def extract_text(file_storage) -> str:
    name = (file_storage.filename or "").lower()
    data = file_storage.read()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
        return "\n".join(pages)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type. Please upload a PDF, .txt or .md file.")


def clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify({"mode": "ai" if llm.has_api_key() else "demo", "model": llm.MODEL})


@app.post("/api/generate")
def generate():
    try:
        text = (request.form.get("text") or "").strip()
        upload = request.files.get("file")
        if upload and upload.filename:
            text = extract_text(upload).strip()
        if len(text) < 200:
            return jsonify({"error": "Add at least a paragraph of notes (200+ characters) to get a useful study pack."}), 400

        n_cards = clamp(request.form.get("cards"), 3, 20, 8)
        n_questions = clamp(request.form.get("questions"), 3, 15, 6)
        language = (request.form.get("language") or "English").strip()[:30]

        note = None
        try:
            pack = llm.generate_pack(text, n_cards, n_questions, language)
        except Exception as exc:  # AI failed -> fall back so the demo never dies
            if not llm.has_api_key():
                raise
            app.logger.exception("AI generation failed")
            note = f"The AI request failed ({type(exc).__name__}), so this pack was built in offline demo mode."
            pack = llm.generate_pack(text, n_cards, n_questions, language, force_demo=True)

        pack["doc_id"] = remember(text)
        # Serverless hosts (Vercel) do not share memory between requests, so the
        # browser keeps the text and sends it back with /api/ask and /api/plan.
        pack["text"] = text[: llm.MAX_CHARS]
        pack["note"] = note
        pack["chars"] = len(text)
        return jsonify(pack)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("generate failed")
        return jsonify({"error": "Something went wrong while reading your notes. Try a different file or paste the text."}), 500


@app.post("/api/ask")
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    text = DOCS.get(body.get("doc_id", "")) or (body.get("text") or "")[: llm.MAX_CHARS]
    if not text:
        return jsonify({"error": "Generate a study pack first, then ask questions about it."}), 400
    if not question:
        return jsonify({"error": "Type a question first."}), 400
    try:
        return jsonify(llm.answer_question(text, question[:500]))
    except Exception:
        app.logger.exception("ask failed")
        return jsonify({"answer": "I couldn't reach the AI service. Check your API key and connection.", "mode": "error"}), 502


@app.post("/api/plan")
def plan():
    body = request.get_json(silent=True) or {}
    days = clamp(body.get("days"), 1, 30, 5)
    weak = [str(t)[:60] for t in (body.get("weak_topics") or [])][:10]
    text = DOCS.get(body.get("doc_id", "")) or (body.get("text") or "")[: llm.MAX_CHARS]
    try:
        return jsonify(llm.make_plan(days, weak, text))
    except Exception:
        app.logger.exception("plan failed")
        return jsonify({"plan": llm._demo_plan(days, weak, text), "mode": "demo"})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "That file is over 10 MB. Try a smaller file or paste the important pages."}), 413


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
