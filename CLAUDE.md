# ScholarBridge — CLAUDE.md

AI-powered platform that translates dense academic papers into plain-English summaries for non-profit workers and connects them with researchers. $0 budget — free tiers only throughout.

---

## Monorepo Layout

```
ScholarBridge/
├── backend/          FastAPI + Python 3.11
│   ├── app/
│   │   ├── config.py           pydantic-settings (all env vars)
│   │   ├── main.py             FastAPI app, lifespan, CORS, router registration
│   │   ├── state.py            shared in-memory pipeline_status/messages dicts
│   │   ├── db/
│   │   │   ├── engine.py       async SQLAlchemy engine + get_db() dependency
│   │   │   ├── models.py       ORM: Paper, Summary, Synthesis
│   │   │   └── init_db.py      create_tables() + additive ALTER TABLE migrations
│   │   ├── models/             Pydantic response/request models
│   │   ├── routers/            FastAPI routers (papers, summaries, synthesis, …)
│   │   └── services/           business logic layer
│   ├── requirements.txt
│   └── .env                    secrets — never commit
├── frontend/         Next.js 14 App Router + TypeScript + Tailwind
└── Makefile          orchestrates both dev servers
```

---

## Quick Start

```bash
# Install everything
make install

# Run backend (from project root — venv auto-activated)
make dev-backend        # http://localhost:8000  docs at /docs

# Run frontend
make dev-frontend       # http://localhost:3000

# Lint + test
make lint
make test-backend
```

`dev-backend` runs from the `backend/` directory so `./scholarbridge.db` resolves correctly.

---

## Environment Variables (`backend/.env`)

```
# Core APIs
GEMINI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=scholarbridge-index
PINECONE_ENVIRONMENT=us-east-1-aws
SEMANTIC_SCHOLAR_API_KEY=...   # optional but raises SS rate limit from 0.3→1 req/s

# Auth
JWT_SECRET_KEY=...
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS — set to Vercel URL in production
FRONTEND_URL=http://localhost:3000

# Database (relative to backend/ dir)
DATABASE_URL=sqlite+aiosqlite:///./scholarbridge.db

# Toggle — set true to run without any API keys
USE_MOCK_API=false
```

---

## Mock Mode

`USE_MOCK_API=true` (or missing `GEMINI_API_KEY`) activates a full offline mode:
- Semantic Scholar → swapped for `MockSemanticScholarService` via `app.dependency_overrides`
- Gemini embedding → zero-vector placeholders (`[0.0] * 768`)
- Pinecone upsert → skipped with a warning log
- LLM summarization/synthesis → deterministic fixture responses written to SQLite

Mock mode is set via `app.dependency_overrides` in `main.py` — no changes needed in routers.

---

## Critical SDK & API Conventions

### google-genai (NOT google-generativeai — deprecated)
```python
from google import genai
from google.genai import types as genai_types

client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options={"api_version": "v1beta"},   # required for preview models
)
# The SDK auto-prepends "models/" — NEVER include it in the model string
client.models.generate_content(model="gemini-2.5-flash", ...)
client.models.embed_content(model="gemini-embedding-001", ...)
```

**Current model strings (no prefix):**
| Use | Model string |
|-----|-------------|
| Embeddings (indexing + search) | `gemini-embedding-001` |
| Summarization | `gemini-2.5-flash` |
| Synthesis | `gemini-2.5-flash` (downgraded from Pro due to quota) |
| Query expansion | `gemini-2.5-flash` |

### Pinecone (pinecone-client 3.x)
- Index: 768-dim cosine, `ServerlessSpec(cloud="aws", region="us-east-1")`
- When querying by metadata filter only (no semantic ranking), pass a dummy zero vector: `embedding=[0.0] * 768`
- `query_vectors()` returns `response.get("matches", [])` — always check for empty list

### Semantic Scholar
- `x-api-key` header required for 1 req/s; unauthenticated = ~0.3 req/s
- Retry with exponential backoff on 429; `SemanticScholarError` raised after exhausted retries
- External IDs (`ARXIV:...`, `DOI:...`) are valid as `paper_id` — SS resolves them
- `paper.paper_id` returned from SS is always the SS internal ID (not the ArXiv ID the user submitted)

---

## ID Handling (Important)

Users submit IDs like `ARXIV:2308.13418`. Semantic Scholar resolves these to internal IDs (e.g., `abc123def`). **The DB always stores the user-submitted ID as `paper_id` and the SS internal ID as `ss_paper_id`** so lookups by either format work.

Pinecone vector metadata uses the SS internal ID (`paper.paper_id`) since that's what was stored at index time. Always use `ss_paper_id` for Pinecone filter queries.

---

## JIT Indexing Pipeline

Triggered by `POST /api/v1/summaries/request`. Runs as `asyncio.create_task()` — fire and forget.

```
PENDING → DOWNLOADING → EXTRACTING → CHUNKING → EMBEDDING → INDEXED → SUMMARIZING → COMPLETE
                                                                                    ↘ FAILED
```

State tracked in `app.state.pipeline_status` (in-memory dict). Poll via `GET /summaries/{id}/status`.

Fallback path: if PDF unavailable or yields < 200 chars → uses `abstract + tldr` → status `ABSTRACT_ONLY` (not FAILED, pipeline continues to INDEXED then SUMMARIZING).

---

## Database

SQLite via `aiosqlite` + async SQLAlchemy. File: `backend/scholarbridge.db` (relative to CWD at server start — must be run from `backend/`).

**Schema:**
- `papers` — paper metadata; `paper_id` = user-supplied ID; `ss_paper_id` = SS internal ID
- `summaries` — one row per paper; JSON columns: `key_findings`, `jargon_glossary`
- `syntheses` — cross-paper meta-analysis; cached by `paper_ids_key` with 1-hour TTL

**Migrations:** `init_db.py` runs `CREATE TABLE IF NOT EXISTS` + a `_MIGRATIONS` list of `ALTER TABLE ADD COLUMN` statements checked via `PRAGMA table_info`. Append here instead of deleting the DB.

If the DB schema gets out of sync: delete `backend/scholarbridge.db` and restart — tables are recreated from the ORM models.

---

## Services

| Service | File | Purpose |
|---------|------|---------|
| `SemanticScholarService` | `semantic_scholar.py` | Paper search + detail fetch |
| `MockSemanticScholarService` | `mock_semantic_scholar.py` | 7 fixture papers for offline dev |
| `PineconeClient` | `pinecone_client.py` | Vector upsert + query |
| `SearchService` | `search_service.py` | Expand → embed → Pinecone → re-rank → SS fallback |
| `SummarizationService` | `summarization_service.py` | "Technical Translator" prompt → DB |
| `SynthesisService` | `synthesis_service.py` | "Senior Research Analyst" prompt → DB |

All services follow the same singleton pattern:
```python
_instance: ServiceClass | None = None
def get_service() -> ServiceClass:
    global _instance
    if _instance is None:
        _instance = ServiceClass()
    return _instance
```

---

## Search Pipeline

`GET /api/v1/papers/search?query=...`

1. Query expansion — Gemini Flash generates 3 academic phrases appended to query
2. Embed expanded query with `gemini-embedding-001` (768 dims)
3. Query Pinecone `top_k = limit * 5`
4. **Similarity threshold** — if best score < `0.5`, treat as 0 results → fallback
5. Deduplicate: best chunk per `paper_id`
6. Hybrid re-rank: `final_score = sim * 0.8 + (citation_count / max_citations) * 0.2`
7. Fallback: if 0 Pinecone results → `SemanticScholarService.search_papers()` with `search_source="semantic_scholar_fallback"`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/api/v1/papers/search` | Semantic search (vector + SS fallback) |
| GET | `/api/v1/papers/{paper_id}` | Full paper detail |
| POST | `/api/v1/summaries/request` | Trigger JIT indexing (idempotent) |
| GET | `/api/v1/summaries/` | Library — all summarised papers |
| GET | `/api/v1/summaries/{paper_id}/status` | Poll pipeline status |
| GET | `/api/v1/summaries/{paper_id}` | Get executive summary |
| POST | `/api/v1/synthesis/` | Cross-paper meta-analysis (2–5 papers) |

---

## Phase Roadmap

- **Phase 0** — Monorepo scaffolding, CI ✅
- **Phase 1** — FastAPI skeleton, Semantic Scholar, JIT pipeline ✅
- **Phase 2.1** — Semantic search service (vector + hybrid re-rank + fallback) ✅
- **Phase 2.2** — Summarization service + SQLite library ✅
- **Phase 2.3** — Synthesis service (cross-paper meta-analysis) ✅
- **Phase 2.4** — Researcher matching
- **Phase 3** — Frontend (Next.js search UI, paper detail, synthesis view)
- **Phase 4** — Auth (JWT), non-profit verification, researcher claiming, inquiry system
- **Phase 5** — Deployment (Render + Vercel)
