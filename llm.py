"""LLM layer for Study Buddy.

Two modes:
  * AI mode   - uses the Anthropic API when ANTHROPIC_API_KEY is set.
  * Demo mode - simple offline text processing, so the app always runs
                (useful when the Wi-Fi at the venue fails).
"""
import json
import os
import re
from collections import Counter

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_CHARS = 24000  # keep prompts small and fast

STOPWORDS = set(
    """a an the and or but if then else when while of in on at to from by for with without
    is are was were be been being as that this these those it its into over under about
    which who whom whose what why how can could should would may might will shall do does
    did done have has had not no nor so than too very also more most such other some any
    each both few many much only own same their there they them he she we you your our
    his her i me my one two three first second""".split()
)


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# --------------------------------------------------------------------------
# Claude helpers
# --------------------------------------------------------------------------
def _call_claude(system: str, user: str, max_tokens: int = 4000) -> str:
    import anthropic  # imported lazily so demo mode works without the package

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON")
    return json.loads(text[start : end + 1])


PACK_SYSTEM = """You are a careful study assistant for students.
Use ONLY the notes the student gives you. Never invent facts that are not in the notes.
Reply with a single JSON object and nothing else (no markdown fences, no commentary)."""

PACK_SCHEMA = """{
  "title": "short title for the material",
  "summary": "a clear summary in 4-6 sentences",
  "key_points": ["5-8 short bullet points"],
  "flashcards": [{"front": "question or term", "back": "concise answer", "topic": "1-3 word topic"}],
  "quiz": [{
      "question": "...",
      "options": ["A text", "B text", "C text", "D text"],
      "answer_index": 0,
      "explanation": "one or two sentences on why the answer is right",
      "topic": "1-3 word topic"
  }]
}"""


def _normalize_pack(raw: dict) -> dict:
    pack = {
        "title": str(raw.get("title") or "Study pack"),
        "summary": str(raw.get("summary") or ""),
        "key_points": [str(p) for p in raw.get("key_points", []) if p],
        "flashcards": [],
        "quiz": [],
    }
    for c in raw.get("flashcards", []):
        if c.get("front") and c.get("back"):
            pack["flashcards"].append(
                {
                    "front": str(c["front"]),
                    "back": str(c["back"]),
                    "topic": str(c.get("topic") or "General"),
                }
            )
    for q in raw.get("quiz", []):
        opts = [str(o) for o in q.get("options", [])][:4]
        try:
            ans = int(q.get("answer_index", 0))
        except (TypeError, ValueError):
            continue
        if q.get("question") and len(opts) >= 2 and 0 <= ans < len(opts):
            pack["quiz"].append(
                {
                    "question": str(q["question"]),
                    "options": opts,
                    "answer_index": ans,
                    "explanation": str(q.get("explanation") or ""),
                    "topic": str(q.get("topic") or "General"),
                }
            )
    return pack


def generate_pack(text: str, n_cards: int, n_questions: int, language: str, force_demo: bool = False) -> dict:
    text = text[:MAX_CHARS]
    if has_api_key() and not force_demo:
        user = (
            f"Write everything in {language}.\n"
            f"Create exactly {n_cards} flashcards and {n_questions} multiple-choice questions "
            f"(4 options each, exactly one correct).\n"
            f"JSON shape:\n{PACK_SCHEMA}\n\nNOTES:\n\"\"\"\n{text}\n\"\"\""
        )
        raw = _parse_json(_call_claude(PACK_SYSTEM, user, max_tokens=5000))
        pack = _normalize_pack(raw)
        if pack["summary"] and (pack["flashcards"] or pack["quiz"]):
            pack["mode"] = "ai"
            return pack
        raise ValueError("Model returned an incomplete study pack")
    pack = _demo_pack(text, n_cards, n_questions)
    pack["mode"] = "demo"
    return pack


def answer_question(text: str, question: str) -> dict:
    text = text[:MAX_CHARS]
    if has_api_key():
        system = (
            "You answer a student's question using ONLY the notes provided. "
            "If the notes do not contain the answer, say so plainly. Keep answers short and clear."
        )
        user = f"NOTES:\n\"\"\"\n{text}\n\"\"\"\n\nQUESTION: {question}"
        return {"answer": _call_claude(system, user, max_tokens=800).strip(), "mode": "ai"}
    return {"answer": _demo_answer(text, question), "mode": "demo"}


def make_plan(days: int, weak_topics: list, text: str) -> dict:
    days = max(1, min(days, 30))
    if has_api_key():
        system = (
            "You build realistic revision plans for students. "
            "Reply with a single JSON object only, no markdown fences."
        )
        user = (
            f"The student has {days} day(s) until the exam.\n"
            f"Weak topics (most missed first): {weak_topics or 'none recorded yet'}.\n"
            f"Study material (excerpt):\n\"\"\"\n{text[:6000]}\n\"\"\"\n\n"
            'JSON shape: {"plan": [{"day": 1, "focus": "short focus", "tasks": ["task", "task"]}]}\n'
            f"Return exactly {days} entries. Put weak topics early and keep the last day for a light revision."
        )
        raw = _parse_json(_call_claude(system, user, max_tokens=2000))
        plan = [
            {
                "day": int(d.get("day", i + 1)),
                "focus": str(d.get("focus", "")),
                "tasks": [str(t) for t in d.get("tasks", [])],
            }
            for i, d in enumerate(raw.get("plan", []))
        ]
        if plan:
            return {"plan": plan, "mode": "ai"}
    return {"plan": _demo_plan(days, weak_topics, text), "mode": "demo"}


# --------------------------------------------------------------------------
# Demo mode (no API key) - extractive heuristics
# --------------------------------------------------------------------------
def _sentences(text: str) -> list:
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if 30 <= len(p.strip()) <= 320]


def _words(s: str) -> list:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-']+", s.lower()) if w not in STOPWORDS and len(w) > 2]


def _top_sentences(text: str, k: int) -> list:
    sents = _sentences(text)
    freq = Counter(w for s in sents for w in _words(s))
    scored = []
    for i, s in enumerate(sents):
        ws = _words(s)
        if not ws:
            continue
        scored.append((sum(freq[w] for w in ws) / (len(ws) ** 0.5), i, s))
    best = sorted(scored, reverse=True)[:k]
    return [s for _, _, s in sorted(best, key=lambda t: t[1])]  # keep original order


def _keyword_of(sentence: str, freq: Counter) -> str:
    cands = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']+", sentence) if w.lower() not in STOPWORDS and len(w) > 4]
    if not cands:
        return ""
    return max(cands, key=lambda w: (freq[w.lower()], len(w)))


def _demo_pack(text: str, n_cards: int, n_questions: int) -> dict:
    sents = _sentences(text)
    if len(sents) < 3:
        raise ValueError("Please provide a bit more text (at least a few full sentences).")
    freq = Counter(w for s in sents for w in _words(s))
    top = _top_sentences(text, max(n_cards, n_questions, 6))
    summary = " ".join(top[:4])
    key_points = top[:6]

    vocab = [w for w, _ in freq.most_common(60) if len(w) > 4]

    cards, quiz = [], []
    for s in top:
        kw = _keyword_of(s, freq)
        if not kw:
            continue
        blanked = re.sub(re.escape(kw), "_____", s, count=1, flags=re.IGNORECASE)
        if len(cards) < n_cards:
            cards.append({"front": blanked, "back": kw, "topic": kw.capitalize()})
        if len(quiz) < n_questions:
            in_sentence = set(_words(s))
            distractors = [w for w in vocab if w.lower() != kw.lower() and w.lower() not in in_sentence][:30]
            # deterministic but varied distractors
            offset = len(quiz) * 3
            picks = (distractors[offset:] + distractors[:offset])[:3]
            if len(picks) < 3:
                continue
            options = picks + [kw.lower()]
            options = [o.capitalize() if kw[0].isupper() else o for o in options]
            order = sorted(range(4), key=lambda i: (i * 7 + len(quiz) * 5) % 4)
            options = [options[i] for i in order]
            answer_index = order.index(3)
            quiz.append(
                {
                    "question": "Fill in the blank: " + blanked,
                    "options": options,
                    "answer_index": answer_index,
                    "explanation": "From your notes: " + s,
                    "topic": kw.capitalize(),
                }
            )
    return {
        "title": "Your study pack (demo mode)",
        "summary": summary,
        "key_points": key_points,
        "flashcards": cards,
        "quiz": quiz,
    }


def _demo_answer(text: str, question: str) -> str:
    q_words = set(_words(question))
    sents = _sentences(text)
    scored = sorted(
        ((len(q_words & set(_words(s))), s) for s in sents),
        key=lambda t: t[0],
        reverse=True,
    )
    best = [s for score, s in scored[:2] if score > 0]
    if not best:
        return "I couldn't find that in your notes. Try different keywords, or add an API key for smarter answers."
    return " ".join(best)


def _demo_plan(days: int, weak_topics: list, text: str) -> list:
    topics = list(weak_topics)
    if not topics:
        freq = Counter(_words(text))
        topics = [w.capitalize() for w, _ in freq.most_common(max(days, 3))]
    plan = []
    for d in range(1, days + 1):
        if d == days and days > 1:
            plan.append(
                {
                    "day": d,
                    "focus": "Light revision",
                    "tasks": ["Skim your summary", "Run through all flashcards once", "Sleep early"],
                }
            )
            continue
        topic = topics[(d - 1) % len(topics)]
        plan.append(
            {
                "day": d,
                "focus": topic,
                "tasks": [
                    f"Re-read your notes on {topic}",
                    f"Do the flashcards tagged '{topic}'",
                    "Take a fresh quiz and check mistakes",
                ],
            }
        )
    return plan
