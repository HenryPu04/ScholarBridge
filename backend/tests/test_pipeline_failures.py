"""
Reliability regression tests for the ingestion pipeline and hybrid ranking.

Pre-patch behaviour (current code)
-----------------------------------
  TestChunkText          — ImportError on _chunk_text (function does not exist yet).
  test_empty_chunks_*    — ImportError for the same reason; if bypassed, the
                           pipeline reaches COMPLETE with 0 vectors (false success).

Post-patch behaviour
---------------------
  All tests pass.

Search re-ranking tests (TestSearchRerankingEdgeCases) pass on BOTH the
pre-patch and post-patch codebase — they are regression guards for
division-by-zero / NaN safety that is already correct in the current code.
"""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.state as pipeline_state
from app.models.paper import Author, OpenAccessPdf, PaperDetail, PaperResult
from app.models.search import SearchResult
from app.models.summary import PipelineStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAPER_ID = "TEST_PAPER_001"
PIPELINE_MOD = "app.services.indexing_pipeline"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_paper(
    *,
    abstract: str | None = None,
    tldr: str | None = None,
    has_pdf: bool = False,
) -> PaperDetail:
    return PaperDetail(
        paper_id=PAPER_ID,
        title="Test Paper",
        abstract=abstract,
        authors=[Author(name="Jane Doe")],
        year=2024,
        citation_count=10,
        fields_of_study=["Computer Science"],
        open_access_pdf=(
            OpenAccessPdf(url="https://example.com/paper.pdf", status="GREEN")
            if has_pdf
            else None
        ),
        tldr=tldr,
    )


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.use_mock_api = True   # no real Gemini/Pinecone calls
    s.gemini_api_key = None
    s.pinecone_api_key = None
    return s


def _make_mock_ss(paper: PaperDetail) -> MagicMock:
    svc = MagicMock()
    svc.get_paper_details = AsyncMock(return_value=paper)
    return svc


def _make_mock_pinecone() -> MagicMock:
    pc = MagicMock()
    pc.upsert_vectors = MagicMock()
    pc.query_vectors = MagicMock(return_value=[])
    return pc


def _make_async_session_factory() -> MagicMock:
    """Minimal async-context-manager stub for AsyncSessionLocal()."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory


def _make_mock_summarization_get() -> MagicMock:
    """get_summarization_service() returning a no-op .summarize()."""
    svc = MagicMock()
    svc.summarize = AsyncMock()
    return MagicMock(return_value=svc)


# ---------------------------------------------------------------------------
# Fixture: wipe shared in-memory state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pipeline_state():
    pipeline_state.pipeline_status.clear()
    pipeline_state.pipeline_messages.clear()
    yield
    pipeline_state.pipeline_status.clear()
    pipeline_state.pipeline_messages.clear()


# ---------------------------------------------------------------------------
# Helper: run the full pipeline with all external I/O mocked
# ---------------------------------------------------------------------------


async def _run_pipeline(paper: PaperDetail, extra_patches: list | None = None) -> None:
    from app.services.indexing_pipeline import run_pipeline  # noqa: PLC0415

    base_patches = [
        patch(f"{PIPELINE_MOD}.get_settings", return_value=_mock_settings()),
        patch(f"{PIPELINE_MOD}.get_semantic_scholar_service",
              return_value=_make_mock_ss(paper)),
        patch(f"{PIPELINE_MOD}.get_pinecone_client",
              return_value=_make_mock_pinecone()),
        patch("app.services.summarization_service.get_summarization_service",
              new=_make_mock_summarization_get()),
        patch("app.db.engine.AsyncSessionLocal",
              new=_make_async_session_factory()),
    ]
    all_patches = base_patches + (extra_patches or [])

    for p in all_patches:
        p.start()
    try:
        await run_pipeline(PAPER_ID)
    finally:
        for p in all_patches:
            p.stop()


# ===========================================================================
# 1.  Unit tests for _chunk_text (new helper extracted during the patch)
#
#     These tests import _chunk_text directly.  On the un-patched codebase
#     that symbol does not exist, so the import raises ImportError — which
#     demonstrates that there is no guard and no testable helper in place.
# ===========================================================================


class TestChunkText:
    """Direct unit tests for the _chunk_text helper (added in the patch)."""

    @staticmethod
    def _ct():
        from app.services.indexing_pipeline import _chunk_text  # noqa: PLC0415
        return _chunk_text

    # ------------------------------------------------------------------ #

    def test_normal_text_produces_nonempty_chunks(self):
        text = "Meaningful research sentence with actual content. " * 50
        chunks = self._ct()(text)
        assert len(chunks) > 0
        assert all(c.strip() for c in chunks)

    def test_whitespace_only_text_produces_empty_list(self):
        """
        All-whitespace text → every chunk strips to "" → chunks == [].
        This is the invariant the new guard in run_pipeline must catch.
        """
        text = "   \t\n  " * 200
        chunks = self._ct()(text)
        assert chunks == []

    def test_empty_string_produces_empty_list(self):
        assert self._ct()("") == []

    def test_max_chunks_cap_is_respected(self):
        from app.services.indexing_pipeline import CHUNK_SIZE, MAX_CHUNKS  # noqa: PLC0415
        text = "x" * (CHUNK_SIZE * (MAX_CHUNKS + 10))
        chunks = self._ct()(text)
        assert len(chunks) == MAX_CHUNKS

    def test_single_word_produces_one_chunk(self):
        assert self._ct()("hello world") == ["hello world"]

    def test_leading_trailing_whitespace_stripped(self):
        text = "   leading and trailing spaces   " * 100
        chunks = self._ct()(text)
        for c in chunks:
            assert c == c.strip()


# ===========================================================================
# 2.  Pipeline integration tests
# ===========================================================================


class TestPipelineFailedState:

    # ------------------------------------------------------------------ #
    # 2a. Existing guard: no abstract + no PDF → FAILED
    #     Passes on BOTH pre-patch and post-patch codebase.
    # ------------------------------------------------------------------ #

    async def test_no_abstract_no_pdf_sets_failed(self):
        """
        Paper has no open-access PDF and no abstract/TLDR.
        The existing 'if not fallback_text' guard must set FAILED.
        """
        paper = _make_paper(abstract=None, tldr=None, has_pdf=False)
        await _run_pipeline(paper)

        assert pipeline_state.pipeline_status[PAPER_ID] == PipelineStatus.FAILED
        msg = pipeline_state.pipeline_messages.get(PAPER_ID, "")
        # The message must be actionable and mention the cause
        assert any(
            kw in msg.lower()
            for kw in ("abstract", "tldr", "pdf", "no pdf", "fallback")
        ), f"Expected actionable FAILED message, got: {msg!r}"

    # ------------------------------------------------------------------ #
    # 2b. Malformed PDF magic bytes + valid abstract → COMPLETE via fallback
    #     Passes on BOTH pre-patch and post-patch codebase.
    # ------------------------------------------------------------------ #

    async def test_bad_pdf_magic_bytes_falls_back_to_abstract(self):
        """
        PDF URL returns HTTP 200 but bytes start with 'GIF89a' (not a PDF).
        Pipeline must fall back to the abstract and complete successfully.
        """
        paper = _make_paper(
            abstract="Comprehensive abstract covering key research findings. " * 6,
            has_pdf=True,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"GIF89a\x00\x00" + b"x" * 300  # bad magic bytes

        mock_http_client = MagicMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.get = AsyncMock(return_value=mock_response)

        await _run_pipeline(
            paper,
            extra_patches=[patch("httpx.AsyncClient", return_value=mock_http_client)],
        )

        status = pipeline_state.pipeline_status.get(PAPER_ID)
        assert status == PipelineStatus.COMPLETE, (
            f"Expected COMPLETE after abstract fallback, got {status}. "
            f"Message: {pipeline_state.pipeline_messages.get(PAPER_ID)}"
        )

    # ------------------------------------------------------------------ #
    # 2c. Empty-chunk guard — NEW behaviour (fails pre-patch, passes post-patch)
    #
    #     PRE-PATCH:  importing _chunk_text raises ImportError → test ERRORs,
    #                 demonstrating that no guard exists.
    #     POST-PATCH: _chunk_text is patched to return [] → pipeline must
    #                 set FAILED with a message mentioning chunks.
    # ------------------------------------------------------------------ #

    async def test_empty_chunks_sets_failed_not_complete(self):
        """
        When _chunk_text returns [] (e.g. whitespace-only text that bypassed
        the extraction length check), run_pipeline MUST set FAILED.

        The leading import acts as a sentinel: if _chunk_text doesn't exist
        the ImportError itself demonstrates the missing guard.
        """
        # Sentinel import — raises ImportError on un-patched code
        from app.services.indexing_pipeline import _chunk_text  # noqa: F401, PLC0415

        paper = _make_paper(
            # Provide a real abstract so the fallback path sets text successfully
            abstract="Legitimate abstract content for this paper. " * 20,
            has_pdf=False,
        )

        empty_chunk_patch = patch(
            f"{PIPELINE_MOD}._chunk_text",
            return_value=[],  # simulate the degenerate case
        )

        await _run_pipeline(paper, extra_patches=[empty_chunk_patch])

        assert pipeline_state.pipeline_status.get(PAPER_ID) == PipelineStatus.FAILED, (
            "Pipeline must transition to FAILED when _chunk_text returns []. "
            f"Actual status: {pipeline_state.pipeline_status.get(PAPER_ID)}"
        )
        msg = pipeline_state.pipeline_messages.get(PAPER_ID, "")
        assert any(
            kw in msg.lower()
            for kw in ("chunk", "empty", "no content", "no indexable", "whitespace")
        ), f"FAILED message must be actionable, got: {msg!r}"


# ===========================================================================
# 3.  Search service hybrid re-ranking edge cases
#
#     These tests verify that citation-normalised scores never produce NaN or
#     raise ZeroDivisionError.  They pass on BOTH pre-patch and post-patch
#     codebase and serve as permanent regression guards.
# ===========================================================================


class TestSearchRerankingEdgeCases:

    @staticmethod
    def _make_service():
        from app.services.search_service import SearchService  # noqa: PLC0415
        from app.services.mock_semantic_scholar import (  # noqa: PLC0415
            get_mock_semantic_scholar_service,
        )
        return SearchService(ss_service=get_mock_semantic_scholar_service())

    @staticmethod
    def _match(paper_id: str, score: float, citation_count: int | None) -> dict:
        return {
            "id": f"{paper_id}__chunk_0",
            "score": score,
            "metadata": {
                "paper_id": paper_id,
                "title": f"Paper {paper_id}",
                "authors": "Alice, Bob",
                "year": 2023,
                "citation_count": citation_count,
                "fields_of_study": [],
                "text": "sample matched text",
                "source": "full_paper",
            },
        }

    @staticmethod
    def _pinecone_mock(matches: list[dict]) -> MagicMock:
        pc = MagicMock()
        pc.query_vectors = MagicMock(return_value=matches)
        return pc

    def _query(self, matches: list[dict]) -> list[SearchResult]:
        svc = self._make_service()
        with patch(
            "app.services.search_service.get_pinecone_client",
            return_value=self._pinecone_mock(matches),
        ):
            return svc._query_pinecone(
                query_embedding=[0.0] * 768,
                limit=10,
                year_min=None,
                year_max=None,
                fields_of_study=[],
            )

    # ------------------------------------------------------------------ #

    def test_empty_pinecone_response_returns_empty_list(self):
        assert self._query([]) == []

    def test_single_result_zero_citations_no_nan(self):
        results = self._query([self._match("P1", score=0.80, citation_count=0)])
        assert len(results) == 1
        score = results[0].relevance_score
        assert not math.isnan(score), "relevance_score must not be NaN"
        assert not math.isinf(score), "relevance_score must not be Inf"
        # 0.80*0.8 + (0/1)*0.2 = 0.64
        assert score == pytest.approx(0.64, abs=0.01)

    def test_single_result_none_citations_treated_as_zero(self):
        results = self._query([self._match("P1", score=0.90, citation_count=None)])
        score = results[0].relevance_score
        assert not math.isnan(score)
        # 0.90*0.8 + 0*0.2 = 0.72
        assert score == pytest.approx(0.72, abs=0.01)

    def test_multiple_results_all_zero_citations_no_nan(self):
        matches = [
            self._match("P1", score=0.80, citation_count=0),
            self._match("P2", score=0.70, citation_count=0),
            self._match("P3", score=0.60, citation_count=0),
        ]
        results = self._query(matches)
        for r in results:
            assert not math.isnan(r.relevance_score)
            assert not math.isinf(r.relevance_score)

    def test_merge_both_inputs_empty_returns_empty(self):
        svc = self._make_service()
        assert svc._merge(pinecone_results=[], ss_papers=[], limit=10) == []

    def test_merge_ss_only_zero_citations_score_is_zero(self):
        ss_paper = PaperResult(paper_id="SS001", title="Zero-citation paper", citation_count=0)
        svc = self._make_service()
        results = svc._merge(pinecone_results=[], ss_papers=[ss_paper], limit=10)
        assert len(results) == 1
        score = results[0].relevance_score
        assert not math.isnan(score)
        assert score == 0.0

    def test_merge_ss_only_none_citations_no_nan(self):
        ss_paper = PaperResult(paper_id="SS002", title="No-citation-count paper", citation_count=None)
        svc = self._make_service()
        results = svc._merge(pinecone_results=[], ss_papers=[ss_paper], limit=10)
        score = results[0].relevance_score
        assert not math.isnan(score)
        assert score == 0.0
