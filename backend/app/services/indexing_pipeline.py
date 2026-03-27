"""
JIT (Just-in-Time) Indexing Pipeline
=====================================
Triggered by: asyncio.create_task(run_pipeline(paper_id))

Pipeline stages
---------------
1. DOWNLOADING  — fetch PDF over HTTP (falls back to abstract on any failure)
2. EXTRACTING   — parse PDF bytes with pypdf, clean whitespace
3. CHUNKING     — fixed-size overlapping character chunks (≈512 tokens each)
4. EMBEDDING    — batch-embed chunks with Gemini text-embedding-004 (768 dims)
5. INDEXED      — upsert vectors to Pinecone with rich metadata

Fallback path: if a PDF cannot be fetched or yields < 200 chars of text, the
pipeline transparently falls back to the paper's abstract + TLDR and sets the
source field to "abstract_only".  Status is set to ABSTRACT_ONLY and the rest
of the stages run normally so the summary router always has vectors to query.

Error handling: the entire pipeline body is wrapped in a broad try/except so
that any unexpected exception sets status to FAILED without crashing the event
loop task.
"""

import asyncio
import io
import logging
import re
from typing import Optional

import httpx
import pypdf

from google import genai
from google.genai import types as genai_types

from app.config import get_settings
from app.models.paper import PaperDetail
from app.models.summary import PipelineStatus
from app import state
from app.services.semantic_scholar import get_semantic_scholar_service
from app.services.pinecone_client import get_pinecone_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunking constants
# ---------------------------------------------------------------------------
CHUNK_SIZE = 2048       # chars — approximately 512 tokens at 4 chars/token
OVERLAP = 200           # chars — approximately 50 tokens
STEP = CHUNK_SIZE - OVERLAP  # = 1848
MAX_CHUNKS = 150

# ---------------------------------------------------------------------------
# Embedding constants
# ---------------------------------------------------------------------------
EMBED_BATCH_SIZE = 10
EMBED_MODEL_PRIMARY  = "gemini-embedding-001"       # SDK prepends models/ automatically
EMBED_MODEL_FALLBACK = "gemini-embedding-2-preview" # newer preview
EMBED_DIMENSIONS = 768  # must match the Pinecone index dimension


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _set_status(
    paper_id: str,
    status: PipelineStatus,
    message: Optional[str] = None,
) -> None:
    """Update shared pipeline state and emit an INFO log line."""
    state.pipeline_status[paper_id] = status
    if message is not None:
        state.pipeline_messages[paper_id] = message
    logger.info(
        "Pipeline [%s] status=%s%s",
        paper_id,
        status.value,
        f" — {message}" if message else "",
    )


def _build_fallback_text(paper: PaperDetail) -> str:
    """Concatenate abstract and TLDR into a single fallback string."""
    parts: list[str] = []
    if paper.abstract:
        parts.append(paper.abstract)
    if paper.tldr:
        parts.append(paper.tldr)
    return " ".join(parts).strip()


# Module-level singletons — initialised once, reused across all pipeline runs.
_genai_client: genai.Client | None = None
_resolved_embed_model: str | None = None


def _get_genai_client() -> genai.Client:
    """Return the shared google-genai client, creating it on first call."""
    global _genai_client
    if _genai_client is None:
        settings = get_settings()
        _genai_client = genai.Client(
            api_key=settings.gemini_api_key,
            # Pin to the stable v1 endpoint explicitly.
            http_options={"api_version": "v1beta"},
        )
        logger.info("google-genai client initialised (api_version=v1).")
    return _genai_client


def _embed_single(text: str) -> list[float]:
    """
    Embed one chunk using the new google-genai SDK.

    Probes EMBED_MODEL_PRIMARY on first call; falls back to EMBED_MODEL_FALLBACK
    on any 404 / model-not-found response and remembers the working model so
    subsequent calls skip the probe entirely.
    """
    global _resolved_embed_model

    client = _get_genai_client()
    candidates = (
        [_resolved_embed_model]
        if _resolved_embed_model
        else [EMBED_MODEL_PRIMARY, EMBED_MODEL_FALLBACK]
    )

    for model in candidates:
        logger.info(
            "Embedding chunk — model=%r  dim=%d  api_version=v1",
            model,
            EMBED_DIMENSIONS,
        )
        try:
            response = client.models.embed_content(
                model=model,
                contents=text,
                config=genai_types.EmbedContentConfig(
                    output_dimensionality=EMBED_DIMENSIONS,
                ),
            )
            _resolved_embed_model = model
            return response.embeddings[0].values
        except Exception as exc:
            exc_str = str(exc).lower()
            if any(sig in exc_str for sig in ("404", "not found", "not_found", "notfound")):
                logger.warning(
                    "Model %r not found (%s) — trying next candidate.", model, exc
                )
                continue
            raise  # auth errors, quota errors, etc. — surface immediately

    raise RuntimeError(
        f"No working embedding model found. Tried: {[EMBED_MODEL_PRIMARY, EMBED_MODEL_FALLBACK]}"
    )


# ---------------------------------------------------------------------------
# Public pipeline entry-point
# ---------------------------------------------------------------------------

async def run_pipeline(paper_id: str) -> None:
    """
    Run the full JIT indexing pipeline for *paper_id*.

    This coroutine is designed to be scheduled with asyncio.create_task().
    It never re-raises — all exceptions are caught and reflected as FAILED
    status so that polling routes can surface the error to the frontend.
    """
    settings = get_settings()
    use_mock = settings.use_mock_api or settings.gemini_api_key is None

    try:
        # ------------------------------------------------------------------
        # Fetch paper metadata from Semantic Scholar
        # ------------------------------------------------------------------
        ss = get_semantic_scholar_service()
        paper: PaperDetail = await ss.get_paper_details(paper_id)

        # Track whether we are working from the PDF or just text fallback
        used_fallback: bool = False
        text: str = ""

        # ==================================================================
        # Stage 1 — DOWNLOADING
        # ==================================================================
        _set_status(paper_id, PipelineStatus.DOWNLOADING)

        pdf_bytes: Optional[bytes] = None

        if paper.open_access_pdf is None:
            # No PDF available — skip straight to fallback
            logger.info(
                "Paper %s has no open-access PDF; will use abstract fallback.",
                paper_id,
            )
        else:
            pdf_url = paper.open_access_pdf.url
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0),
                    follow_redirects=True,
                ) as client:
                    response = await client.get(pdf_url)

                if response.status_code != 200:
                    logger.warning(
                        "Paper %s: PDF fetch returned HTTP %s for %s — using fallback.",
                        paper_id,
                        response.status_code,
                        pdf_url,
                    )
                elif not response.content.startswith(b"%PDF"):
                    logger.warning(
                        "Paper %s: URL %s did not return a PDF (bad magic bytes) — using fallback.",
                        paper_id,
                        pdf_url,
                    )
                else:
                    pdf_bytes = response.content

            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Paper %s: HTTP error fetching PDF from %s — using fallback. Error: %s",
                    paper_id,
                    pdf_url,
                    exc,
                )

        # ==================================================================
        # Stage 2 — EXTRACTING
        # ==================================================================
        _set_status(paper_id, PipelineStatus.EXTRACTING)

        if pdf_bytes is not None:
            try:
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                pages_text: list[str] = []
                for page in reader.pages:
                    try:
                        pages_text.append(page.extract_text() or "")
                    except Exception:
                        continue
                raw_text = "\n".join(pages_text)
                raw_text = re.sub(r"\s+", " ", raw_text).strip()

                if len(raw_text) < 200:
                    logger.warning(
                        "Paper %s: extracted PDF text is too short (%d chars) — using fallback.",
                        paper_id,
                        len(raw_text),
                    )
                else:
                    text = raw_text

            except Exception as exc:
                logger.warning(
                    "Paper %s: pypdf extraction failed — using fallback. Error: %s",
                    paper_id,
                    exc,
                )

        # If we still have no usable text, engage fallback
        if not text:
            used_fallback = True
            fallback_text = _build_fallback_text(paper)

            if not fallback_text:
                _set_status(
                    paper_id,
                    PipelineStatus.FAILED,
                    "No PDF text and no abstract/TLDR available; cannot index paper.",
                )
                logger.error(
                    "Paper %s: fallback text is empty — pipeline cannot continue.",
                    paper_id,
                )
                return

            _set_status(
                paper_id,
                PipelineStatus.ABSTRACT_ONLY,
                "Using abstract/TLDR as fallback — PDF unavailable or unreadable.",
            )
            text = fallback_text

        # ==================================================================
        # Stage 3 — CHUNKING
        # ==================================================================
        _set_status(paper_id, PipelineStatus.CHUNKING)

        chunks: list[str] = []
        for start in range(0, len(text), STEP):
            chunk = text[start : start + CHUNK_SIZE].strip()
            if chunk:
                chunks.append(chunk)
            if len(chunks) >= MAX_CHUNKS:
                break

        logger.info(
            "Paper %s: produced %d chunks from %d chars of text.",
            paper_id,
            len(chunks),
            len(text),
        )

        # ==================================================================
        # Stage 4 — EMBEDDING
        # ==================================================================
        _set_status(paper_id, PipelineStatus.EMBEDDING)

        all_embeddings: list[list[float]]

        if use_mock:
            logger.warning(
                "Paper %s: mock mode — generating zero-vector embeddings (not real). "
                "Set USE_MOCK_API=false and provide GEMINI_API_KEY for production.",
                paper_id,
            )
            all_embeddings = [[0.0] * EMBED_DIMENSIONS for _ in chunks]
        else:
            all_embeddings = []

            for i in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[i : i + EMBED_BATCH_SIZE]

                for chunk_text in batch:
                    all_embeddings.append(_embed_single(chunk_text))

                # Rate-limit pause between batches (not after the last one)
                if i + EMBED_BATCH_SIZE < len(chunks):
                    await asyncio.sleep(1)

        # ==================================================================
        # Stage 5 — INDEXED
        # ==================================================================
        authors_str = ", ".join(a.name for a in paper.authors)
        source = "abstract_only" if used_fallback else "full_paper"

        vectors: list[dict] = []
        for i, (chunk_text, embedding) in enumerate(zip(chunks, all_embeddings)):
            vectors.append(
                {
                    "id": f"{paper_id}__chunk_{i}",
                    "values": embedding,
                    "metadata": {
                        "paper_id": paper_id,
                        "chunk_index": i,
                        "text": chunk_text[:1000],  # Pinecone metadata 1 KB limit
                        "title": paper.title,
                        "authors": authors_str,
                        "year": paper.year,
                        "source": source,
                        "fields_of_study": paper.fields_of_study or [],
                        "citation_count": paper.citation_count,
                    },
                }
            )

        if use_mock:
            logger.warning(
                "Paper %s: mock mode — skipping Pinecone upsert (%d vectors).",
                paper_id,
                len(vectors),
            )
        else:
            get_pinecone_client().upsert_vectors(vectors)

        _set_status(paper_id, PipelineStatus.INDEXED)
        logger.info(
            "Paper %s indexed: %d chunks, source=%s",
            paper_id,
            len(chunks),
            source,
        )

    except Exception as exc:
        _set_status(paper_id, PipelineStatus.FAILED, str(exc))
        logger.exception(
            "Pipeline failed for paper '%s': %s",
            paper_id,
            exc,
        )
        # Do NOT re-raise — this coroutine runs inside asyncio.create_task()
        # and an unhandled exception there would only log an obscure warning.
