# Study Buddy

Upload notes or a PDF chapter and get a summary, flashcards, a quiz, a "chat with your notes"
box and a revision plan. Topics you miss in quizzes are remembered in the browser and scheduled first.

## Run it

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python app.py
```

Open http://localhost:5000

## AI mode vs demo mode

- **Demo mode** (no key): works offline using simple text processing. Great as a safety net at the venue.
- **AI mode**: put `ANTHROPIC_API_KEY` in `.env`. Get a key at https://console.anthropic.com
  The badge in the top-right shows which mode is active. If an AI call fails, the app falls back to demo mode
  and tells the user.

## Project structure

```
app.py              Flask routes, file upload and PDF text extraction
llm.py              Claude prompts, JSON validation, offline demo fallback
templates/index.html
public/static/style.css
public/static/app.js   Tabs, flashcards, quiz, chat, plan, weak topics (localStorage)
sample_notes.txt    Paste this to test quickly (or use the "Try sample notes" button)
```

## API

| Route | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Returns `ai` or `demo` mode |
| `/api/generate` | POST (form) | `file` or `text`, plus `cards`, `questions`, `language` |
| `/api/ask` | POST (JSON) | `doc_id`, `question` |
| `/api/plan` | POST (JSON) | `days`, `weak_topics`, `doc_id` |

## Ideas to extend it for the hackathon

- Save packs per user with SQLite and add login.
- Spaced repetition: show "Still learning" cards again sooner.
- Syllabus mode for a specific exam (JEE, NEET, university subject).
- Voice: read summaries aloud with the browser's SpeechSynthesis API.
- Deploy on Render or Railway so judges can open a live link.

## Demo tips

1. Keep a real chapter PDF ready, plus the sample notes as a backup.
2. Show the flow in order: upload, summary, flashcards, one quiz miss, plan.
3. Mention the offline fallback: it never fails on stage.

## Deploy on Vercel

1. Push this folder to a GitHub repository (see the steps below).
2. On vercel.com choose **Add New > Project**, import the repository and click **Deploy**.
   Vercel detects the Flask app (`app.py` with a variable named `app`) automatically.
3. Optional AI mode: in **Project Settings > Environment Variables** add `ANTHROPIC_API_KEY`, then redeploy.

Notes for Vercel: static files must stay in `public/`, and uploads are limited to about 4.5 MB per request.

## Push to GitHub

```bash
git init
git add .
git commit -m "Study Buddy first version"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/study-buddy.git
git push -u origin main
```
