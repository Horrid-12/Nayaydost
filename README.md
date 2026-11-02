# NyayaDost (न्यायदोस्त)

**Legal notices, in language you actually speak.**

NyayaDost reads an Indian legal notice or FIR, removes the legalese, and turns it into a citizen-friendly plan: what the notice means, which date matters, what to do next, and where to get free legal help. It works in English, हिन्दी, मराठी, ગુજરાતી, தமிழ், తెలుగు, and বাংলা.

The app is built as a small, production-minded FastAPI service with a framework-free HTML/CSS/JavaScript frontend. It runs completely offline in demo mode, and uses Sarvam AI for translation, text-to-speech, and speech-to-text when an API key is configured.

> **Not legal advice.** NyayaDost explains documents in plain language. It is not a law firm. Verify important steps with a licensed advocate or your District Legal Services Authority (DLSA). The free national legal-aid helpline is **15100**.

---

## What is included

- **Notice analysis** — detects nine common Indian notice types and extracts the sender, notice date, amount, legal basis, and response deadline.
- **Citizen breakdown** — a plain-language summary, deadline cards with a live countdown, a printable checklist, a glossary, and a reply draft.
- **Seven Indian languages** — English, Hindi, Marathi, Gujarati, Tamil, Telugu, and Bengali, with native-script UI labels and localized summaries.
- **Three input paths** — paste text, upload a text-based PDF with an in-browser preview, or dictate/upload audio.
- **Audio explanations** — Sarvam Bulbul when configured; a labelled demo tone plus device speech synthesis in offline mode. The player supports play/pause, scrubbing, and 0.75×/1×/1.25× speeds.
- **NyayaGuide** — practical, notice-specific guides with steps, documents to keep, timelines, common mistakes, and warning signs.
- **Legal Aid Finder** — a demo DLSA directory covering 36 states and Union Territories, with eligibility, documents, and application steps.
- **Theme switching** — archival parchment light mode and an executive legal-chamber dark mode, saved in `localStorage`.
- **Defensive error handling** — every API route and every frontend fetch produces a short, citizen-friendly message instead of a stack trace.
- **Security headers** — CSP, `X-Content-Type-Options`, `X-Frame-Options`, referrer policy, permissions policy, request IDs, and no-store caching for API responses.
- **In-memory uploads** — PDFs are parsed in memory and discarded. No database and no document storage.

The original Streamlit prototype in `app.py` is left untouched. NyayaDost is the FastAPI application alongside it.

---

## Quick start

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure the app

```bash
cp .env.example .env
```

The app starts without editing `.env`. Leave `SARVAM_API_KEY` empty to use the offline demo.

### 4. Run the server

```bash
python main.py
```

Open <http://127.0.0.1:8000/>.

For automatic reload during development:

```bash
uvicorn main:app --reload
```

`uvicorn server.main:app --reload` also works. The API documentation is at <http://127.0.0.1:8000/api/docs>.

### 5. Run the tests

```bash
./venv/bin/python -m unittest discover -s tests -v
./venv/bin/python scripts/smoke_test.py
```

The smoke test starts its own temporary server, exercises every API area, and shuts it down. To test a running instance instead:

```bash
./venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

---

## Offline mode vs. Sarvam live mode

The app chooses its mode at startup:

| Mode | When | What happens |
| --- | --- | --- |
| `offline-demo` | `SARVAM_API_KEY` is empty | The deterministic rulebook handles analysis. Translation uses a legal phrasebook, TTS returns a soft demo WAV, and STT returns a labelled demo transcript. |
| `live` | `SARVAM_API_KEY` is set | Mayura translation, Bulbul speech, and Saaras transcription are called. If a live call fails, the response is marked `degraded` and a clearly labelled fallback is returned. |

The UI always shows the current mode and labels fallback output. Mock audio is never presented as real speech.

### Sarvam environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SARVAM_API_KEY` | empty | Enables live Sarvam calls. Never commit a real key. |
| `SARVAM_BASE_URL` | `https://api.sarvam.ai` | Sarvam API base URL. |
| `SARVAM_TRANSLATE_MODEL` | `mayura:v1` | Translation model. |
| `SARVAM_TTS_MODEL` | `bulbul:v2` | Text-to-speech model. |
| `SARVAM_STT_MODEL` | `saaras:v4` | Speech-to-text model. |
| `SARVAM_TTS_SPEAKER` | `anushka` | Default Bulbul speaker. |
| `SARVAM_TRANSLATE_TIMEOUT` | `15` | Translation timeout in seconds. |
| `SARVAM_TTS_TIMEOUT` | `25` | TTS timeout in seconds. |
| `SARVAM_STT_TIMEOUT` | `35` | STT timeout in seconds. |
| `SARVAM_MAX_RETRIES` | `1` | Retry count for transient Sarvam failures. |

### App and limit variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` enables production defaults and HSTS over HTTPS. |
| `APP_DEBUG` | `true` outside production | Enables Uvicorn reload when using `python main.py`. |
| `APP_HOST` | `127.0.0.1` | Bind host for `python main.py`. |
| `APP_PORT` | `8000` | Bind port for `python main.py`. |
| `TRUST_PROXY` | `false` | Read `X-Forwarded-For` for rate limiting when behind a trusted proxy. |
| `MAX_UPLOAD_MB` | `10` | PDF upload limit. |
| `MAX_PDF_PAGES` | `60` | Maximum pages read from a PDF. |
| `MAX_TEXT_CHARS` | `50000` | Maximum pasted notice length. |
| `MAX_TTS_CHARS` | `900` | Maximum spoken text length. |
| `MAX_TRANSLATE_CHARS` | `5000` | Maximum translation length. |
| `MAX_STT_MB` | `10` | Audio upload limit. |
| `RATE_LIMIT_ANALYZE` | `30` | Analyses allowed per client per window. |
| `RATE_LIMIT_VOICE` | `25` | Voice/translation requests per client per window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window length. |

---

## Demo flow

1. Open the home page. The header shows **Offline demo** unless Sarvam is configured.
2. In **Explain a notice**, choose a language, then press **Load** on one of the nine sample notices.
3. Press **Explain this notice**. The staged status reads through parsing, distillation, and translation while the analysis runs.
4. Review the **Citizen Breakdown**:
   - 📌 What This Notice Means
   - ⏳ Critical Deadlines with days remaining and the source of each date
   - ✅ Immediate Next Steps with a persistent checklist
5. Switch to **Original Legalese**, **Glossary**, or **Reply Draft**.
6. Press **Load audio** for a spoken explanation. In offline mode, use **Use device voice** to hear the full text through the browser.
7. Change the language selector. The existing analysis is re-run in the new language.
8. Try **Upload PDF** with a text-based PDF. The selected PDF appears in an in-browser preview before analysis.
9. Open **NyayaGuide** to read a practical guide for the selected notice type.
10. Open **Legal Aid** and choose a state and district to find the demo DLSA entry and application steps.

Useful sample inputs live in `server/data/samples.json`. The PDF fixture in `tests/fixtures/sample_notice.pdf` is a one-page text PDF suitable for upload testing.

---

## API overview

All API routes are under `/api`. Errors use a consistent JSON shape:

```json
{
  "ok": false,
  "error": {
    "code": "not_pdf",
    "message": "That file does not look like a PDF.",
    "hint": "Upload a PDF file, or paste the notice text in the text tab.",
    "request_id": "req_…",
    "details": null
  }
}
```

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health, version, mode, locales, and IST time. |
| `GET` | `/api/bootstrap?language=mr` | Languages, notice types, samples, and client limits. |
| `POST` | `/api/analyze` | Analyze pasted text. |
| `POST` | `/api/analyze/upload` | Analyze a PDF upload (`multipart/form-data`). |
| `POST` | `/api/translate` | Sarvam Mayura translation or offline phrasebook fallback. |
| `POST` | `/api/tts` | Sarvam Bulbul speech or demo WAV fallback. |
| `POST` | `/api/stt` | Sarvam Saaras transcription or demo transcript fallback. |
| `GET` | `/api/guide/{notice_type}?language=ta` | NyayaGuide content for a notice type. |
| `GET` | `/api/legal-aid/options` | States, districts, helpline, and website. |
| `GET` | `/api/legal-aid?state=Maharashtra&district=Pune` | Matched or approximate DLSA entry. |

Notice type IDs:

`cheque_bounce`, `rent_eviction`, `loan_recovery`, `consumer`, `maintenance`, `property`, `employment`, `tax`, `generic`.

Language codes:

`en`, `hi`, `mr`, `gu`, `ta`, `te`, `bn`.

### Example: analyze pasted text

```bash
curl -sS http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "LEGAL NOTICE UNDER SECTION 138 OF THE NEGOTIABLE INSTRUMENTS ACT, 1881. You issued a cheque for Rs. 1,85,000 which was returned unpaid. Pay within 15 days of receipt of this notice, failing which criminal proceedings will be initiated.",
    "language": "mr",
    "source_name": "Pasted notice"
  }'
```

### Example: analyze a PDF

```bash
curl -sS http://127.0.0.1:8000/api/analyze/upload \
  -F 'file=@tests/fixtures/sample_notice.pdf;type=application/pdf' \
  -F 'language=en'
```

### Example: find a DLSA

```bash
curl -sS 'http://127.0.0.1:8000/api/legal-aid?state=Maharashtra&district=Pune'
```

---

## Project structure

```text
.
├── main.py                     # python main.py launcher + uvicorn main:app entry point
├── app.py                      # original Streamlit prototype (untouched)
├── requirements.txt
├── .env.example
├── server/
│   ├── main.py                 # FastAPI app, middleware, static files, error pages
│   ├── config.py               # environment-driven settings
│   ├── errors.py               # typed citizen-safe errors
│   ├── models.py               # Pydantic request/response contracts
│   ├── routers/
│   │   └── api.py              # JSON API routes and rate limiting
│   ├── services/
│   │   ├── simplifier.py       # detection, extraction, deadlines, localized response
│   │   ├── document_parser.py  # defensive in-memory PDF parsing
│   │   ├── sarvam_service.py   # Mayura, Bulbul, Saaras + offline fallbacks
│   │   ├── localization.py     # locale loading and normalization
│   │   ├── content.py          # samples, NyayaGuide, legal-aid directory
│   │   ├── audio.py            # generated demo WAV
│   │   └── ratelimit.py        # in-process sliding-window limiter
│   └── data/
│       ├── locales/            # en, hi, mr, gu, ta, te, bn
│       ├── samples.json
│       ├── guides.json
│       └── legal_aid.json
├── templates/
│   ├── index.html
│   └── error.html
├── static/
│   ├── css/styles.css
│   ├── js/app.js
│   ├── js/theme-init.js
│   └── favicon.svg
├── scripts/
│   └── smoke_test.py
└── tests/
    ├── test_core.py
    └── fixtures/
        ├── sample_notice.pdf
        └── sample_notice.txt
```

### How the analysis works

1. **Normalize and parse.** Pasted text is trimmed. PDFs are read in memory, checked for size/type/pages, extracted with `pypdf`, and normalized so wrapped words and numbers are reconstructed.
2. **Detect the notice type.** A weighted rulebook scores legal phrases, statutes, and remedies across nine categories.
3. **Extract facts.** Dates, notice date, amount (including Indian grouping and PDF line wraps), sender, and response deadline are pulled out with guarded regular expressions.
4. **Build the citizen answer.** The selected locale supplies the summary frame, deadline labels, checklist steps, glossary, and reply draft. Deadlines are calculated in IST and include the source of the date.
5. **Render safely.** The frontend inserts every API/user string with `textContent`, never `innerHTML`.

The rulebook is deliberately deterministic: it works without an API key, produces repeatable demo results, and does not send the notice to an LLM.

---

## Privacy and safety

- Uploaded PDFs and audio are read into memory and discarded after the request. The app has no document database.
- The local server does not call Sarvam for analysis. Translation and speech are separate, explicit actions.
- When Sarvam is configured, translation/TTS/STT requests send only the text or audio needed for that action.
- API responses are `Cache-Control: no-store`.
- The app never renders user text with `innerHTML`.
- Rate limiting is in-process and per client. For a multi-worker production deployment, replace it with a shared store such as Redis.
- The demo legal-aid directory is indicative. Always call **15100** or the local DLSA to confirm the address, phone number, and hours.

---

## Error handling

The backend distinguishes expected, citizen-safe errors (`AppError`, `DocumentError`, `RateLimitError`) from unexpected failures. Expected errors keep their friendly message and hint. Unexpected failures are logged with a request ID and returned as a generic 500 message without internal details.

The frontend wraps every request in one `api()` helper with a timeout and a single error shape. Network failures, timeouts, 4xx responses, and malformed JSON all become an on-screen alert and toast. When a new analysis fails, the previous result is kept visible.

PDF-specific failures are explained directly:

- empty file
- not a PDF
- too large
- password-protected
- damaged/unreadable
- no pages
- scanned image with no selectable text
- pages that could not be extracted

Scanned PDFs tell the citizen to copy the text or use a phone text scanner instead.

---

## Limitations and next steps

- The analysis engine is a curated rulebook for nine notice families, not a general legal AI. Unfamiliar notices get a generic explanation and a warning.
- The legal-aid directory is a demo dataset, not a live government feed.
- NyayaGuide articles are English-first with a localized native summary. Full article translation would be the next content milestone.
- Live Sarvam behavior depends on API access, quotas, and model availability. Offline fallbacks keep the demo usable.
- For production, add a shared rate-limit store, structured request logging/telemetry, and a reviewed legal-content workflow.

---

## License and attribution

Built for the Sarvam AI hackathon. The legal explanations are educational demo content. Sarvam AI provides Mayura, Bulbul, and Saaras when configured. Fonts are loaded from Google Fonts with local serif/sans fallbacks when the network is unavailable.
