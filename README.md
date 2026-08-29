# LinkedIn Profile API

A hosted HTTPS API that accepts a LinkedIn profile URL and returns the profile's
information as structured JSON: name, headline, location, about, experience,
education, skills, certifications, languages, and profile images.

Built around an **adaptive extraction engine**: every field is produced by an
ordered chain of extractors with automatic fallback, field-level provenance and
confidence (`?debug=true`), a profile **diff/snapshot** API, and service
**metrics** — so if LinkedIn changes one page, the whole API degrades gracefully
instead of breaking.

Built for an engineering hiring challenge by reverse-engineering LinkedIn's
web platform. **For evaluation / educational use only** — scraping LinkedIn is
subject to their Terms of Service; rate-limit and use sparingly.

---

## Quick start

```bash
# 1. install
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 2. configure your LinkedIn session cookie
cp .env.example .env      # then set LINKEDIN_LI_AT

# 3. run
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Try it:

```bash
curl -X POST http://localhost:8000/api/v1/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/abhishekpathak0907/"}'
```

Docs: http://localhost:8000/docs (Swagger UI) · http://localhost:8000/redoc

---

## API

### `POST /api/v1/profile`

Request:

```json
{ "url": "https://www.linkedin.com/in/<vanity>/" }
```

Response (`200`):

```json
{
  "name": "Abhishek Pathak",
  "headline": "AI Investments @ Sorin | PeerCapital | IndigoEdge | IIT Roorkee",
  "location": "Bengaluru, Karnataka, India",
  "about": "I am an Investment Associate at an early stage Venture Capital firm...",
  "connections": null,
  "profile_urn": "urn:li:fsd_profile:ACoAABrF3E8BwSc4tj53QGXfYxb-BuGlfVfDUhA",
  "vanity_name": "abhishekpathak0907",
  "profile_images": ["https://media.licdn.com/dms/image/.../profile-displayphoto..."],
  "experience": [ { "title": "...", "company": "...", "date_range": "2022 - Present" } ],
  "education": [ { "school": "Indian Institute of Technology, Roorkee" } ],
  "skills": [ { "name": "..." } ],
  "certifications": [ { "name": "..." } ],
  "languages": [ { "name": "..." } ],
  "scraped_at": "2026-08-28T03:43:13Z",
  "cached": false
}
```

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Invalid / non-profile URL |
| 404 | Profile not found, private, or doesn't exist |
| 502 | Scraping failed (network / parse error) |
| 503 | LinkedIn auth expired or blocked the request |

Responses are cached in-memory for 15 minutes to reduce load.

### `POST /api/v1/profile?debug=true`

Returns the same profile plus an `metadata` object giving full visibility into
how each field was extracted:

```json
{
  "profile": { ...same as above... },
  "metadata": {
    "sources": {
      "experience": { "source": "details_page", "confidence": 0.96, "status": "success", "duration_ms": 2 },
      "skills":     { "source": "details_page", "confidence": 0.9,  "status": "success", "duration_ms": 1 }
    },
    "timings_ms": { "experience": 2, "total": 22875 },
    "pages_visited": 6,
    "warnings": [ { "section": "experience", "reason": "section_not_found", "fallback_attempted": true } ],
    "schema_health": { "experience": "healthy", "education": "healthy", "skills": "healthy" }
  }
}
```

- `sources.<field>.source`: `main_profile` | `details_page` | `flight_data` | `missing`
- `schema_health`: `healthy` when data was found (or legitimately absent),
  `degraded` when a section was expected but returned nothing and fell back.
- `warnings` reports any fallback that was triggered — the first sign of a
  LinkedIn UI change.

### `POST /api/v1/profile/diff`

Compare a fresh scrape against a previous profile snapshot:

```json
{
  "url": "https://www.linkedin.com/in/abhishekpathak0907/",
  "previous": { "headline": "...", "skills": [ {"name": "PHP"} ], ... }
}
```

```json
{
  "url": "...",
  "changed": true,
  "changes": {
    "headline": { "before": "Software Engineer at X", "after": "Senior Software Engineer at Y" },
    "skills":   { "added": [ {"name": "Rust"} ], "removed": [ {"name": "PHP"} ] },
    "experience": { "added": [...], "removed": [...], "modified": [ {"before": {...}, "after": {...}} ] }
  }
}
```

List items are matched on a stable identity key (`title|company` for
experience, `school` for education, `name` for skills/certs/languages), so
reordering doesn't produce false add/remove noise.

### `POST /api/v1/profile/snapshot` · `GET /api/v1/profile/changes`

```bash
curl -X POST http://localhost:8000/api/v1/profile/snapshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/abhishekpathak0907/"}'
# → {"url": "...", "vanity_name": "abhishekpathak0907", "saved": true}

curl "http://localhost:8000/api/v1/profile/changes?url=https://www.linkedin.com/in/abhishekpathak0907/"
# → {"url": "...", "vanity_name": "...", "has_previous": true, "changes": {...}}
```

`snapshot` stores the latest profile per vanity name in memory; `changes`
scrapes it again and diffs against the stored snapshot. The store is
**in-memory** (resets on restart — a documented limitation of free hosting).

### `GET /metrics`

```json
{
  "uptime_seconds": 70,
  "profiles_scraped": 1,
  "success": 1,
  "partial": 0,
  "failed": 0,
  "success_rate": 100.0,
  "avg_scrape_ms": 22875,
  "cache_hit_rate": 0.0,
  "field_extraction_success_rate": { "experience": 100.0, "education": 100.0 }
}
```

### `GET /health`

Liveness probe used by the host.

---

## Architecture

```
                    ┌─ MainProfileExtractor (name, headline, location, about, urn, images)
                    ├─ ExperienceDetailsExtractor     ┐
Profile URL ──page──┼─ EducationDetailsExtractor      │ primary (/details/* pages)
                    ├─ SkillsDetailsExtractor         │
                    ├─ CertificationsDetailsExtractor ┘
                    └─ FlightDataExtractor (fallback: greps embedded RSC payload)
                            ↓
                      ExtractionEngine
                      (per-field extractor chains + fallback)
                            ↓
                      Validation + confidence scoring + schema drift detection
                            ↓
                        ProfileData (+ optional metadata / diff / metrics)
```

Each field has an **ordered chain** of extractors. The engine tries them in
sequence and keeps the first *valid* result:

```python
FIELD_EXTRACTORS = {
    "experience": [ExperienceDetailsExtractor(), FlightDataExtractor("experience")],
    "education":  [EducationDetailsExtractor(),  FlightDataExtractor("education")],
    "skills":     [SkillsDetailsExtractor(),     FlightDataExtractor("skills")],
    ...
}
```

If the primary `/details/*` page changes or fails, the engine automatically
falls through to the next strategy instead of the whole API breaking. Every
page is captured exactly once; extractors operate on the captured text/HTML, so
fallbacks cost no extra network round-trips.

Confidence is a function of source + completeness
(`details_page` > `main_profile` > `flight_data`, penalised for missing
dates/empty lists). Schema drift detection compares actual results against
expected minimums (e.g. a company in the top card implies experience should be
non-empty) and reports `degraded` + a warning when a section comes back empty
despite being expected.

### Reverse-engineering notes

Modern LinkedIn profile pages are split into two data tiers:

1. **Server-rendered top card + About.** The first `GET /in/{vanity}/`
   response HTML (fetched with an authenticated `li_at` cookie) contains the
   name, headline, location, connection count, profile photo URLs and the full
   About text — no extra requests needed.

2. **Section detail pages.** Experience, Education, Skills, Certifications and
   Languages are served by dedicated server-rendered URLs that LinkedIn's own
   UI navigates to on click:
   `/in/{vanity}/details/experience/`, `/details/education/`, `/details/skills/`,
   `/details/certifications/`, `/details/languages/`. Each renders clean,
   structured text (job title → company → dates → location, school → degree →
   dates, etc.).

   The initial profile HTML intentionally omits these sections (they load via
   LinkedIn's internal RSC endpoint `POST /flagship-web/rsc-action/actions/component`
   with volatile `profileComponentState` bindings), so scraping the main page
   alone misses them.

Because of that, the scraper uses **Playwright (headless Chromium)**:

- seeds a browser context with the `li_at` session cookie,
- loads the profile URL and parses the top card + About from the DOM,
- visits each `/details/*` page and parses the sections line-wise into the
  response model.

`li_at` is read from the environment (`LINKEDIN_LI_AT`) — credentials are never
committed. The `auth.py` module isolates all cookie handling.

---

## Deployment (Render, free tier)

`render.yaml` is included:

- Build: `pip install -r requirements.txt && python -m playwright install chromium`
  (note: **no `--with-deps`** — Render's free tier can't `sudo`, and its Python
  runtime already ships the Chromium system libraries)
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Env vars: `LINKEDIN_LI_AT` (required) and optionally `SCRAPE_MODE` (default
  `http`; set to `playwright` for full JS-hydrated sections on a paid plan)
- Health check: `/health`

Create a Web Service from this repo in Render (or use the Blueprint) and set
the env vars. Render's default Python is 3.14; the repo's `.python-version`
pins 3.12 so all dependencies (incl. `greenlet`) resolve to prebuilt wheels.

### Scrape modes

| Mode | Data | Memory | Notes |
|------|------|--------|-------|
| `http` (default) | name, headline, location, connections, about\*, experience, education\*, profile images, URN | ~tens of MB | Fast (~5s). Sections that LinkedIn only renders via JavaScript (education\*, skills, certifications, languages) report `degraded` + a `requires_javascript` warning. Works on Render free tier. |
| `playwright` | everything, incl. skills/certs/languages | high (Chromium) | Full data, but exceeds the 512MB free-tier budget on heavy pages. Use on a paid plan (`SCRAPE_MODE=playwright`). |

\* Availability varies: `about` and `education` are server-rendered for some
profiles and JS-hydrated for others, so HTTP mode may report them as missing.

The adaptive engine is what makes this acceptable: each field has an ordered
extractor chain, and when the primary strategy can't produce valid data (e.g.
the raw HTML lacks a JS-hydrated section), it falls through to the next
strategy and surfaces a clear `schema_health`/`warnings` signal instead of
silently returning garbage.

---

## Known limitations

- **Terms of Service**: automated access to LinkedIn may violate their ToS.
  This project is an evaluation artifact — keep request volume low.
- **Session expiry**: the `li_at` cookie eventually expires; requests then
  return `503 AUTH_FAILED` until it is refreshed.
- **Private / locked profiles**: sections behind a wall return `404` or partial
  data.
- **Fragile selectors**: LinkedIn uses hashed CSS classes; the scraper relies
  on visible section headings and DOM structure, which can break when LinkedIn
  ships a redesign.
- **Anti-bot**: heavy scraping from one session/IP can trigger LinkedIn's bot
  detection (reCAPTCHA / authwall). The in-memory cache helps, but it does not
  fully prevent this.
- **Snapshot volatility**: the snapshot store is in-memory and resets on server
  restart (free hosting has no persistent disk), so `/profile/changes` only
  works while the process stays up.
- **Free-tier cold start**: on Render's free plan the service sleeps after ~15
  min of inactivity; first request may take ~30–60s.
- **Free-tier memory (512MB)**: the default HTTP mode fits comfortably. The
  Playwright mode (full skills/certs/languages) can exceed the budget on heavy
  profiles and OOM — use it on a paid plan.
