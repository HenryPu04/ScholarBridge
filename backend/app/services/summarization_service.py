"""
Summarization Service — Phase 2.2
===================================
Converts indexed paper chunks into a plain-English ExecutiveSummary via Gemini 2.5 Flash.

Pipeline:
1. Idempotency check — return cached DB row if it exists
2. Upsert paper metadata into `papers` table
3. Query Pinecone for top-5 chunks for this paper_id
   Fallback: use abstract + TLDR if Pinecone has no chunks
4. Build context string and call Gemini 2.5 Flash (Technical Translator prompt)
5. Parse JSON response, write to `summaries` table
6. Return ExecutiveSummary Pydantic model

Mock mode: skips the Gemini call; writes a deterministic fixture summary so the
idempotency path and DB writes can be tested without API credentials.
"""

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Paper, Summary
from app.models.paper import PaperDetail
from app.models.summary import ExecutiveSummary
from app.services.indexing_pipeline import _get_genai_client

logger = logging.getLogger(__name__)

FLASH_MODEL = "gemini-2.5-flash"   # SDK auto-prepends "models/" — do NOT include prefix

_SYSTEM_PROMPT = """\
You are a Technical Translator — a specialist who converts dense academic research \
into clear, actionable intelligence for non-profit program managers, grant writers, \
and field teams.

Your audience has deep domain expertise in their mission area but NO advanced \
scientific training. Write at a 10th-grade reading level. Use active voice. \
Be specific, not vague.

You will receive the most relevant excerpts from an academic paper. Return a single \
JSON object with EXACTLY these keys — no markdown, no code fences, no explanation \
outside the JSON:

{
  "problem_statement": "One paragraph (3-5 sentences). What gap or problem does this research address? Why does it matter to practitioners? Write as if explaining to a program director.",

  "key_findings": [
    "Lead with the result, not the method. What changed? By how much? Be specific (e.g., '42% reduction in child malnutrition over 18 months').",
    "Use plain numbers, not statistical jargon ('significant decrease' → '31% drop').",
    "Focus on what practitioners can act on.",
    "(optional fourth finding)",
    "(optional fifth finding)"
  ],

  "practical_implications": "One paragraph (3-5 sentences). If this research is correct, what should a non-profit DO differently? Lead with action: 'Organizations should...', 'Field teams can...', 'This evidence supports...'",

  "methodology_note": "One sentence. How was this studied? (e.g., 'Researchers ran a 2-year randomized trial across 14 villages in Kenya.')",

  "confidence_note": "One sentence. How much should practitioners trust this? Consider sample size, design, and replication. (e.g., 'Moderate confidence — single-country study, not yet replicated.')",

  "reading_time_minutes": 3,

  "jargon_glossary": {
    "technical term": "Plain-English definition in one complete sentence — not just a synonym.",
    "another term": "Definition."
  }
}

Rules:
- Return ONLY valid JSON. No markdown, no code fences, no preamble.
- key_findings MUST be a JSON array of 3-5 strings.
- jargon_glossary MUST be a JSON object with 3-6 entries.
- Every jargon definition must be a complete sentence.
- reading_time_minutes should be an integer estimate (total word count divided by 200).
- If a field cannot be determined from the provided text, write: "Not determinable from available excerpts."
- Never hallucinate citations, statistics, or author names.\
"""

_MOCK_SUMMARY_FIELDS = {
    "problem_statement": (
        "Agricultural soils worldwide are losing organic matter faster than they can recover, "
        "threatening long-term food security. Many smallholder farmers lack access to evidence-based "
        "guidance on regenerative practices suited to their local conditions. This research addresses "
        "that gap by testing low-cost cover-cropping systems across diverse dryland environments."
    ),
    "key_findings": [
        "Cover-cropped plots retained 38% more topsoil moisture during the dry season compared to bare-soil controls.",
        "Soil organic carbon increased by 0.4 percentage points after two growing seasons — enough to measurably improve water-holding capacity.",
        "Legume cover crops outperformed grass mixes by 22% on nitrogen fixation, reducing the need for synthetic fertiliser inputs.",
    ],
    "practical_implications": (
        "Organizations running dryland farming programs should prioritize legume cover crops — particularly "
        "cowpea and velvet bean — in their seed distribution kits. Field teams can introduce a simple "
        "two-season trial protocol to help farmers observe soil-health improvements themselves, building "
        "local buy-in. This evidence supports allocating budget for cover-crop seed subsidies ahead of the "
        "main planting season."
    ),
    "methodology_note": (
        "Researchers conducted a 3-year randomized field trial across 12 dryland farming communities, "
        "comparing four cover-crop species against a bare-soil control."
    ),
    "confidence_note": (
        "High confidence within the study region — large sample size and multi-year design; "
        "replication in other agro-climatic zones is recommended before broad generalization."
    ),
    "reading_time_minutes": 3,
    "jargon_glossary": {
        "soil organic carbon": (
            "The carbon stored in decomposed plant and animal material in soil — higher levels mean "
            "the soil holds more water and nutrients."
        ),
        "nitrogen fixation": (
            "A process where certain plants (especially legumes) capture nitrogen gas from the air "
            "and convert it into a form that enriches the soil, reducing the need for chemical fertilisers."
        ),
        "dryland farming": (
            "Growing crops in regions that receive less than 500 mm of rainfall per year, relying "
            "on soil moisture management rather than irrigation."
        ),
    },
}


class SummarizationService:
    """
    Orchestrates LLM summarization with DB-backed idempotency and caching.
    """

    async def summarize(
        self,
        paper: PaperDetail,
        source: str,
        db: AsyncSession,
        requested_paper_id: str | None = None,
    ) -> ExecutiveSummary:
        """
        Generate (or retrieve cached) ExecutiveSummary for *paper*.

        Args:
            paper:              Full paper detail from Semantic Scholar.
            source:             "full_paper" or "abstract_only".
            db:                 Active async DB session (injected by caller).
            requested_paper_id: The ID the user originally supplied (e.g. "ARXIV:2301.12345").
                                If provided this is used as the DB primary key so that
                                subsequent lookups with the same ID resolve correctly.
                                Falls back to paper.paper_id when not supplied.

        Returns:
            Populated ExecutiveSummary Pydantic model.
        """
        # Use the user-supplied ID as the canonical DB key so that queries
        # with the same ID (ArXiv, DOI, etc.) always resolve.
        paper_id = requested_paper_id or paper.paper_id
        ss_paper_id = paper.paper_id  # Semantic Scholar internal ID (may differ)

        # ------------------------------------------------------------------
        # Step 1 — Idempotency check
        # ------------------------------------------------------------------
        cached = await self._fetch_cached_summary(paper_id, paper, db)
        if cached is not None:
            logger.info("Summary cache hit for paper_id=%s — skipping LLM call.", paper_id)
            return cached

        # ------------------------------------------------------------------
        # Step 2 — Upsert paper metadata
        # ------------------------------------------------------------------
        await self._upsert_paper(paper, db, paper_id=paper_id, ss_paper_id=ss_paper_id)

        # ------------------------------------------------------------------
        # Step 3 — Retrieve top-5 Pinecone chunks
        # ------------------------------------------------------------------
        # Always query Pinecone with the SS internal ID — that is what was
        # stored in vector metadata during indexing.
        context = self._build_context(paper, source, pinecone_paper_id=ss_paper_id)

        # ------------------------------------------------------------------
        # Step 4 — Call Gemini (or generate mock)
        # ------------------------------------------------------------------
        settings = get_settings()
        use_mock = settings.use_mock_api or settings.gemini_api_key is None

        if use_mock:
            logger.warning(
                "Paper %s: mock mode — using fixture summary (not real LLM output).", paper_id
            )
            fields = _MOCK_SUMMARY_FIELDS
        else:
            fields = await self._call_gemini(paper_id, context)

        # ------------------------------------------------------------------
        # Step 5 — Persist to DB
        # ------------------------------------------------------------------
        reading_time = fields.get("reading_time_minutes")
        if not isinstance(reading_time, int):
            reading_time = max(1, len(context.split()) // 200)

        summary_row = Summary(
            paper_id=paper_id,
            problem_statement=fields["problem_statement"],
            key_findings=json.dumps(fields["key_findings"]),
            practical_implications=fields["practical_implications"],
            methodology_note=fields.get("methodology_note"),
            confidence_note=fields.get("confidence_note"),
            reading_time_minutes=reading_time,
            source=source,
            jargon_glossary=json.dumps(fields["jargon_glossary"]),
        )
        db.add(summary_row)
        await db.commit()
        await db.refresh(summary_row)

        logger.info("Summary written to DB for paper_id=%s.", paper_id)

        return self._row_to_model(summary_row, paper)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_cached_summary(
        self,
        paper_id: str,
        paper: PaperDetail,
        db: AsyncSession,
    ) -> Optional[ExecutiveSummary]:
        result = await db.execute(
            select(Summary).where(Summary.paper_id == paper_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_model(row, paper)

    async def _upsert_paper(
        self,
        paper: PaperDetail,
        db: AsyncSession,
        paper_id: str,
        ss_paper_id: str,
    ) -> None:
        """Insert paper metadata; silently skip if paper_id already exists."""
        authors_json = json.dumps([a.name for a in paper.authors])
        fields_json = json.dumps(paper.fields_of_study or [])

        stmt = (
            sqlite_insert(Paper)
            .values(
                paper_id=paper_id,
                ss_paper_id=ss_paper_id,
                title=paper.title,
                authors=authors_json,
                year=paper.year,
                abstract=paper.abstract,
                fields_of_study=fields_json,
                citation_count=paper.citation_count,
            )
            .on_conflict_do_nothing(index_elements=["paper_id"])
        )
        await db.execute(stmt)
        await db.commit()

    def _build_context(self, paper: PaperDetail, source: str, pinecone_paper_id: str) -> str:
        """
        Retrieve top-5 Pinecone chunks for this paper and assemble a context string.
        Falls back to abstract + TLDR if Pinecone returns nothing.

        Args:
            pinecone_paper_id: The Semantic Scholar internal ID — this is what was
                               stored in Pinecone vector metadata during indexing.
        """
        context_parts: list[str] = [
            f"Title: {paper.title}",
            f"Authors: {', '.join(a.name for a in paper.authors)}",
            f"Year: {paper.year or 'Unknown'}",
        ]

        # Attempt Pinecone retrieval (only in non-mock mode; client may not exist in mock mode)
        chunks: list[str] = []
        try:
            from app.services.pinecone_client import get_pinecone_client
            from app.config import get_settings as _gs
            if not _gs().use_mock_api:
                from app.services.indexing_pipeline import EMBED_DIMENSIONS
                matches = get_pinecone_client().query_vectors(
                    embedding=[0.0] * EMBED_DIMENSIONS,  # dummy vector — filter drives the result
                    top_k=5,
                    filter={"paper_id": {"$eq": pinecone_paper_id}},
                )
                chunks = [m["metadata"].get("text", "") for m in matches if m.get("metadata", {}).get("text")]
        except Exception as exc:
            logger.warning("Could not retrieve Pinecone chunks for context: %s", exc)

        if chunks:
            context_parts.append("\n--- Most Relevant Excerpts ---")
            for i, chunk in enumerate(chunks, 1):
                context_parts.append(f"[Excerpt {i}]\n{chunk}")
        else:
            # Fallback to abstract + TLDR
            if paper.abstract:
                context_parts.append(f"\nAbstract:\n{paper.abstract}")
            if paper.tldr:
                context_parts.append(f"\nTLDR:\n{paper.tldr}")

        return "\n\n".join(context_parts)

    async def _call_gemini(self, paper_id: str, context: str) -> dict:
        """Call Gemini 1.5 Flash and return parsed JSON fields."""
        client = _get_genai_client()
        prompt = f"{_SYSTEM_PROMPT}\n\n---\n\n{context}"

        try:
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()

            # Strip markdown code fences if the model ignores our instruction
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0].strip()

            fields = json.loads(raw)

            # Validate required keys
            required = {
                "problem_statement", "key_findings",
                "practical_implications", "jargon_glossary",
            }
            missing = required - fields.keys()
            if missing:
                raise ValueError(f"Gemini response missing required keys: {missing}")

            # Normalise types
            if isinstance(fields.get("key_findings"), str):
                fields["key_findings"] = [fields["key_findings"]]
            if isinstance(fields.get("jargon_glossary"), list):
                # Convert [{term, definition}] to {term: definition} if model deviated
                fields["jargon_glossary"] = {
                    item.get("term", f"term_{i}"): item.get("definition", "")
                    for i, item in enumerate(fields["jargon_glossary"])
                    if isinstance(item, dict)
                }

            logger.info("Gemini summary generated for paper_id=%s.", paper_id)
            return fields

        except json.JSONDecodeError as exc:
            logger.error("Gemini returned non-JSON for paper_id=%s: %s", paper_id, exc)
            raise RuntimeError(f"Gemini returned non-JSON output: {exc}") from exc
        except Exception as exc:
            logger.error("Gemini call failed for paper_id=%s: %s", paper_id, exc)
            raise

    def _row_to_model(self, row: Summary, paper: PaperDetail) -> ExecutiveSummary:
        return ExecutiveSummary(
            paper_id=row.paper_id,
            title=paper.title,
            problem_statement=row.problem_statement,
            key_findings=json.loads(row.key_findings),
            practical_implications=row.practical_implications,
            methodology_note=row.methodology_note or "",
            confidence_note=row.confidence_note or "",
            reading_time_minutes=row.reading_time_minutes or 1,
            source=row.source,
            jargon_glossary=json.loads(row.jargon_glossary),
        )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_summarization_service_instance: SummarizationService | None = None


def get_summarization_service() -> SummarizationService:
    global _summarization_service_instance
    if _summarization_service_instance is None:
        _summarization_service_instance = SummarizationService()
    return _summarization_service_instance
