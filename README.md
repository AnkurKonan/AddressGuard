# AddressGuard API

A FastAPI service for address field cleanup, completeness checks, basic postal-code format checks, **India PIN → state/district matching** (official India Post data), and batch validation.
> **Accuracy note:** Format and completeness checks only, plus India PIN cross-check against the India Post directory. This does **not** prove an address exists, is occupied, or is deliverable.

## Features

- `GET /` — service information
- `GET /health` — health check
- `POST /v1/validate` — validate and normalize one address
- `POST /v1/normalize` — normalize address fields
- `POST /v1/batch-validate` — validate up to 100 addresses per request
- India PIN intelligence (offline India Post directory)
- Optional API-key protection (`ADDRESSGUARD_API_KEY`)
- RapidAPI proxy-secret support (`MARKETPLACE_PROXY_SECRET`)

---

## Deploy on Cloudflare Workers (recommended)

This project is set up for **Cloudflare Python Workers**.

### Prerequisites

- [Node.js](https://nodejs.org/) (for wrangler)
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A Cloudflare account

### 1. Install dependencies

```bash
uv sync
```

Or without uv:

```bash
pip install -r requirements.txt
npm install -g wrangler
```

### 2. Local development (Workers runtime)

```bash
uv run pywrangler dev
```

Then open http://localhost:8787/health

### 3. Deploy

```bash
uv run pywrangler deploy
```

Or:

```bash
npx wrangler deploy
```

### 4. Set secrets (production)

```bash
npx wrangler secret put ADDRESSGUARD_API_KEY
npx wrangler secret put MARKETPLACE_PROXY_SECRET
```

Leave them unset only for open public testing.

### 5. Point RapidAPI at your Worker URL

Use the `*.workers.dev` URL (or a custom domain) as the base URL in the RapidAPI marketplace listing.

---

## Local development (classic uvicorn)

Still works for tests and local coding:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs

```bash
pytest
```

---

## Authentication

| Header | When |
|--------|------|
| `X-API-Key` | Matches `ADDRESSGUARD_API_KEY` |
| `X-RapidAPI-Proxy-Secret` | Matches `MARKETPLACE_PROXY_SECRET` (RapidAPI gateway) |

If **neither** env var is set, auth is disabled (open endpoints).

---

## Project structure

```
addressguard_api/
├── src/
│   └── main.py          # FastAPI app + Cloudflare Workers entrypoint
├── app/
│   └── main.py          # Thin re-export for local uvicorn / pytest
├── tests/
│   └── test_api.py
├── wrangler.toml        # Cloudflare Workers config
├── pyproject.toml       # Python deps for Workers (pywrangler)
├── requirements.txt
└── README.md
```

---

## Cloudflare free-tier notes

- **100,000 requests / day** shared across your account (all Workers).
- No cold starts / sleep (unlike Render free).
- CPU time is limited (~10 ms soft budget for free); this API is light enough for normal single-address calls.
- Batch endpoint (up to 100 addresses) is heavier — keep free-tier quotas small on RapidAPI.

---

## Example request

```bash
curl -X POST https://YOUR-WORKER.workers.dev/v1/validate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{
    "address_line1": "12 MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postal_code": "560001",
    "country_code": "IN"
  }'
```

---

## License

Proprietary — your terms apply when listing on a marketplace.
