"""
Synthesis Service — Phase 2.3
================================
Cross-paper meta-analysis using Gemini 2.5 Pro.

Pipeline:
1. Validate: 2-5 paper_ids supplied
2. Derive order-independent cache key from paper_ids
3. DB cache lookup with 1-hour TTL
4. Fetch existing summaries from SQLite — 422 if any are missing
5. Build multi-paper context string
6. Call Gemini 2.5 Pro (Meta-Analyst / Senior Research Analyst prompt)
7. Parse + validate JSON response
8. Persist to `syntheses` table
9. Return SynthesisResult

Mock mode: returns a deterministic fixture (no Gemini call).
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Summary, Synthesis
from app.models.synthesis import SynthesisResult
from app.services.indexing_pipeline import _get_genai_client

logger = logging.getLogger(__name__)

PRO_MODEL = "gemini-2.5-pro"   # SDK auto-prepends "models/" — do NOT include prefix
CACHE_TTL = timedelta(hours=1)

_SYSTEM_PROMPT = """\
You are a Senior Research Analyst specializing in evidence synthesis for non-profit \
organizations. Your role is to compare multiple academic studies and produce a unified, \
actionable intelligence briefing that helps program managers make evidence-based decisions.

You will receive structured plain-English summaries of multiple academic papers. \
Analyze them together and return a single JSON object with EXACTLY these keys — \
no markdown, no code fences, no explanation outside the JSON:

{
  "consensus_findings": [
    "A concrete claim all (or most) papers agree on — specific, not generic.",
    "Another shared finding — name what converges and why it matters to practitioners."
  ],

  "conflicting_evidence": [
    "A specific point where one study found X but another found Y — name the tension clearly.",
    "Another disagreement or knowledge gap — explain why a practitioner should care."
  ],

  "combined_recommendation": "2-4 sentences. Based on the total weight of evidence, what should a non-profit program manager DO? Lead with the strongest supported action. Acknowledge uncertainty where it exists. Active voice: 'Organizations should...', 'Prioritize...', 'Avoid...'",

  "evidence_strength": "Strong | Moderate | Preliminary — followed by a colon and one sentence explaining the rating based on: number of studies, study designs (RCTs > observational), geographic diversity, and consistency of findings."
}

Rules:
- Return ONLY valid JSON. No markdown, no code fences, no preamble.
- consensus_findings: JSON array of 2-5 concrete, specific strings.
- conflicting_evidence: JSON array of 1-4 strings. If papers genuinely agree on everything, write: ["No meaningful conflicts identified across these studies."]
- combined_recommendation: a single string (one paragraph). Active voice. Specific, not vague.
- evidence_strength: starts with exactly one of "Strong", "Moderate", or "Preliminary", followed by a colon and one sentence.
- Never hallucinate paper titles, author names, statistics, or findings not present in the provided summaries.
- Do not introduce information not found in the input summaries.\
"""

_MOCK_SYNTHESIS_FIELDS = {
    "consensus_findings": [
        "Cover cropping and soil health interventions consistently improve water retention by 30-40% across dryland environments.",
        "Legume-based cover crops deliver measurable nitrogen fixation benefits that reduce synthetic fertiliser dependency in smallholder settings.",
        "Two-season minimum trial periods are required before soil organic carbon improvements become statistically detectable.",
    ],
    "conflicting_evidence": [
        "One study found cowpea outperformed velvet bean on nitrogen fixation by 22%, while another showed equivalent performance under higher rainfall conditions — context matters.",
        "Studies disagree on whether cost subsidies or farmer training drives higher adoption rates, suggesting the bottleneck varies by region.",
    ],
    "combined_recommendation": (
        "Organizations should prioritize cowpea and velvet bean cover crop distributions in dryland programs, "
        "pairing seed kits with a structured two-season observation protocol to build local evidence and farmer buy-in. "
        "Budget planning should account for subsidies in the first season, with evidence from these studies suggesting "
        "adoption rates double when seed costs are reduced by at least 50%. Avoid over-generalizing results to high-rainfall "
        "contexts without additional validation."
    ),
    "evidence_strength": (
        "Moderate: Multiple studies with consistent directional findings, but geographic diversity is limited "
        "and RCT-level replication across different agro-climatic zones is still needed."
    ),
}


def _make_cache_key(paper_ids: list[str]) -> str:
    """Order-independent, dedup-safe cache key."""
    return "|".join(sorted(set(paper_ids)))


class SynthesisService:
    async def synthesize(
        self,
        paper_ids: list[str],
        db: AsyncSession,
    ) -> SynthesisResult:
        cache_key = _make_cache_key(paper_ids)

        # ------------------------------------------------------------------
        # Step 1 — Cache lookup with TTL
        # ------------------------------------------------------------------
        result = await db.execute(
            select(Synthesis).where(Synthesis.paper_ids_key == cache_key)
        )
        cached_row = result.scalar_one_or_none()

        if cached_row is not None:
            age = datetime.now(timezone.utc) - cached_row.created_at.replace(tzinfo=timezone.utc)
            if age < CACHE_TTL:
                logger.info(
                    "Synthesis cache hit for key=%r (age=%s) — skipping LLM call.",
                    cache_key,
                    age,
                )
                return self._row_to_model(cached_row, cached=True)
            # Expired — delete and regenerate
            await db.execute(delete(Synthesis).where(Synthesis.paper_ids_key == cache_key))
            await db.commit()
            logger.info("Synthesis cache expired for key=%r — regenerating.", cache_key)

        # ------------------------------------------------------------------
        # Step 2 — Fetch summaries; 422 if any are missing
        # ------------------------------------------------------------------
        result = await db.execute(
            select(Summary).where(Summary.paper_id.in_(paper_ids))
        )
        found_rows = result.scalars().all()
        found_ids = {row.paper_id for row in found_rows}
        missing = [pid for pid in paper_ids if pid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"The following paper_ids have no summary yet: {missing}. "
                       "Use POST /summaries/request to index and summarise them first.",
            )

        # ------------------------------------------------------------------
        # Step 3 — Build multi-paper context
        # ------------------------------------------------------------------
        context = self._build_context(found_rows)

        # ------------------------------------------------------------------
        # Step 4 — Call Gemini Pro (or return mock)
        # ------------------------------------------------------------------
        settings = get_settings()
        use_mock = settings.use_mock_api or settings.gemini_api_key is None

        if use_mock:
            logger.warning("Synthesis: mock mode — returning fixture synthesis.")
            fields = _MOCK_SYNTHESIS_FIELDS
        else:
            fields = await self._call_gemini(cache_key, context)

        # ------------------------------------------------------------------
        # Step 5 — Persist
        # ------------------------------------------------------------------
        synthesis_row = Synthesis(
            paper_ids_key=cache_key,
            paper_ids=json.dumps(paper_ids),
            consensus_findings=json.dumps(fields["consensus_findings"]),
            conflicting_evidence=json.dumps(fields["conflicting_evidence"]),
            combined_recommendation=fields["combined_recommendation"],
            evidence_strength=fields["evidence_strength"],
        )
        db.add(synthesis_row)
        await db.commit()
        await db.refresh(synthesis_row)

        logger.info("Synthesis written to DB for key=%r.", cache_key)
        return self._row_to_model(synthesis_row, cached=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_context(self, summary_rows: list[Summary]) -> str:
        parts: list[str] = [
            f"You are analyzing {len(summary_rows)} academic papers. "
            f"Here are their plain-English summaries:\n"
        ]
        for i, row in enumerate(summary_rows, 1):
            findings = json.loads(row.key_findings)
            findings_text = "\n".join(f"  - {f}" for f in findings)
            parts.append(
                f"--- Paper {i} (ID: {row.paper_id}) ---\n"
                f"Problem: {row.problem_statement}\n"
                f"Key Findings:\n{findings_text}\n"
                f"Practical Implications: {row.practical_implications}"
            )
        return "\n\n".join(parts)

    async def _call_gemini(self, cache_key: str, context: str) -> dict:
        client = _get_genai_client()
        prompt = f"{_SYSTEM_PROMPT}\n\n---\n\n{context}"

        try:
            response = client.models.generate_content(
                model=PRO_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()

            # Strip markdown fences if the model ignores our instruction
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0].strip()

            fields = json.loads(raw)

            required = {"consensus_findings", "conflicting_evidence", "combined_recommendation", "evidence_strength"}
            missing_keys = required - fields.keys()
            if missing_keys:
                raise ValueError(f"Gemini response missing keys: {missing_keys}")

            # Normalise: ensure list fields are lists
            for list_field in ("consensus_findings", "conflicting_evidence"):
                if isinstance(fields.get(list_field), str):
                    fields[list_field] = [fields[list_field]]

            logger.info("Gemini synthesis generated for cache_key=%r.", cache_key)
            return fields

        except json.JSONDecodeError as exc:
            logger.error("Gemini returned non-JSON for synthesis key=%r: %s", cache_key, exc)
            raise RuntimeError(f"Gemini returned non-JSON output: {exc}") from exc
        except Exception as exc:
            logger.error("Gemini synthesis call failed for key=%r: %s", cache_key, exc)
            raise

    def _row_to_model(self, row: Synthesis, cached: bool) -> SynthesisResult:
        return SynthesisResult(
            paper_ids=json.loads(row.paper_ids),
            consensus_findings=json.loads(row.consensus_findings),
            conflicting_evidence=json.loads(row.conflicting_evidence),
            combined_recommendation=row.combined_recommendation,
            evidence_strength=row.evidence_strength,
            created_at=row.created_at.isoformat(),
            cached=cached,
        )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_synthesis_service_instance: SynthesisService | None = None


def get_synthesis_service() -> SynthesisService:
    global _synthesis_service_instance
    if _synthesis_service_instance is None:
        _synthesis_service_instance = SynthesisService()
    return _synthesis_service_instance
