# LinkedIn Profile API

A hosted HTTPS API that accepts a LinkedIn profile URL and returns the profile's
information as structured JSON: name, headline, location, about, experience,
education, skills, certifications, languages, and profile images.

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

### `GET /health`

Liveness probe used by the host.

---

## Approach (reverse-engineering notes)

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

- Build: `pip install -r requirements.txt && python -m playwright install --with-deps chromium`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Env vars: `LINKEDIN_LI_AT` and optionally `LINKEDIN_JSESSIONID` (set in the
  Render dashboard, not in the repo)
- Health check: `/health`

Create a Blueprint from this repo in Render and set the two env vars.

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
- **Free-tier cold start**: on Render's free plan the service sleeps after ~15
  min of inactivity; first request may take ~30–60s.
