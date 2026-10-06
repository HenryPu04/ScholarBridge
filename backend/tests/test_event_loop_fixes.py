"""
Tests verifying that the three event-loop / config fixes are in place.

1. search_service.py  — _query_pinecone is dispatched via asyncio.to_thread
2. indexing_pipeline.py — each _embed_single call is dispatched via asyncio.to_thread
3. frontend/lib/api.ts  — BASE reads NEXT_PUBLIC_API_URL and falls back correctly
"""

import pathlib
import re
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import app.state as pipeline_state
from app.models.paper import Author, OpenAccessPdf, PaperDetail
from app.models.summary import PipelineStatus

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PAPER_ID = "THREAD_TEST_001"
PIPELINE_MOD = "app.services.indexing_pipeline"
SEARCH_MOD = "app.services.search_service"
FAKE_EMBEDDING = [0.1] * 768


# ---------------------------------------------------------------------------
# Fixture: reset shared pipeline state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pipeline_state():
    pipeline_state.pipeline_status.clear()
    pipeline_state.pipeline_messages.clear()
    yield
    pipeline_state.pipeline_status.clear()
    pipeline_state.pipeline_messages.clear()


# ===========================================================================
# 1.  Search Service — Pinecone query dispatched via asyncio.to_thread
# ===========================================================================


class TestSearchPineconeThreadDelegation:
    """
    Verify that SearchService.search() calls asyncio.to_thread(self._query_pinecone, ...)
    rather than invoking _query_pinecone synchronously on the event-loop thread.
    """

    @staticmethod
    def _make_service():
        from app.services.search_service import SearchService  # noqa: PLC0415
        from app.services.mock_semantic_scholar import (  # noqa: PLC0415
            get_mock_semantic_scholar_service,
        )
        return SearchService(ss_service=get_mock_semantic_scholar_service())

    async def test_query_pinecone_dispatched_via_to_thread(self):
        """
        When a valid query_embedding is present, search() must await
        asyncio.to_thread(self._query_pinecone, ...).
        Passing a real list for the embedding ensures the Pinecone branch
        is entered (query_embedding is not None).
        """
        svc = self._make_service()

        # The return value of to_thread is what search() will use as
        # pinecone_results; returning [] keeps _merge simple.
        mock_to_thread = AsyncMock(return_value=[])

        with (
            patch(f"{SEARCH_MOD}.asyncio.to_thread", mock_to_thread),
            # Skip real Gemini calls: supply a pre-built embedding directly.
            patch(f"{SEARCH_MOD}._get_genai_client") as mock_genai,
            # Skip real SS calls.
            patch.object(
                svc._ss, "search_papers", new=AsyncMock(return_value=[])
            ),
        ):
            # Patch embed_content to return our fake embedding so that
            # query_embedding is not None and the to_thread branch is reached.
            mock_client = MagicMock()
            mock_embed_response = MagicMock()
            mock_embed_response.embeddings = [MagicMock(values=FAKE_EMBEDDING)]
            mock_client.models.embed_content.return_value = mock_embed_response
            mock_client.models.generate_content.return_value = MagicMock(
                text="phrase one\nphrase two\nphrase three"
            )
            mock_genai.return_value = mock_client

            # Inject settings that enable real (non-mock) path
            mock_settings = MagicMock()
            mock_settings.use_mock_api = False
            mock_settings.gemini_api_key = "fake-key"

            with patch(f"{SEARCH_MOD}.get_settings", return_value=mock_settings):
                await svc.search("cover crops", limit=5)

        # Assert to_thread was called at least once with _query_pinecone as
        # the first positional argument (bound method on svc).
        assert mock_to_thread.called, (
            "asyncio.to_thread was never called — _query_pinecone is running "
            "synchronously on the event loop thread."
        )
        first_call_func = mock_to_thread.call_args_list[0].args[0]
        assert first_call_func == svc._query_pinecone, (
            f"asyncio.to_thread was called with {first_call_func!r} instead of "
            "svc._query_pinecone."
        )

    async def test_query_pinecone_not_called_when_embedding_fails(self):
        """
        When the embedding step raises an exception, query_embedding stays
        None and asyncio.to_thread must NOT be called at all.
        """
        svc = self._make_service()
        mock_to_thread = AsyncMock(return_value=[])

        with (
            patch(f"{SEARCH_MOD}.asyncio.to_thread", mock_to_thread),
            patch(f"{SEARCH_MOD}._get_genai_client") as mock_genai,
            patch.object(
                svc._ss, "search_papers", new=AsyncMock(return_value=[])
            ),
        ):
            mock_client = MagicMock()
            mock_client.models.embed_content.side_effect = RuntimeError("quota exceeded")
            mock_client.models.generate_content.return_value = MagicMock(text="")
            mock_genai.return_value = mock_client

            mock_settings = MagicMock()
            mock_settings.use_mock_api = False
            mock_settings.gemini_api_key = "fake-key"

            with patch(f"{SEARCH_MOD}.get_settings", return_value=mock_settings):
                results = await svc.search("cover crops", limit=5)

        assert not mock_to_thread.called, (
            "asyncio.to_thread must not be called when query_embedding is None."
        )
        # Should still return results (SS fallback)
        assert isinstance(results, list)


# ===========================================================================
# 2.  Indexing Pipeline — each _embed_single dispatched via asyncio.to_thread
# ===========================================================================


class TestPipelineEmbedThreadDelegation:
    """
    Verify that run_pipeline() calls asyncio.to_thread(_embed_single, chunk)
    once per chunk when running in non-mock (real embedding) mode.
    """

    @staticmethod
    def _make_paper(abstract: str) -> PaperDetail:
        return PaperDetail(
            paper_id=PAPER_ID,
            title="Thread Test Paper",
            abstract=abstract,
            authors=[Author(name="Alice")],
            year=2024,
            citation_count=5,
            fields_of_study=[],
            open_access_pdf=None,
            tldr=None,
        )

    async def test_embed_single_dispatched_via_to_thread_per_chunk(self):
        """
        Each chunk in the embedding loop must be processed via
        asyncio.to_thread(_embed_single, chunk_text), not called directly.

        We use an abstract long enough to produce exactly 2 chunks so we
        can count the to_thread calls precisely.
        """
        from app.services.indexing_pipeline import (  # noqa: PLC0415
            CHUNK_SIZE,
            EMBED_BATCH_SIZE,
            _embed_single,
        )

        # Build text that produces exactly 2 chunks (slightly over CHUNK_SIZE)
        two_chunk_text = "word " * (CHUNK_SIZE // 5 + 10)
        paper = self._make_paper(abstract=two_chunk_text)

        # to_thread must return a coroutine-compatible value; AsyncMock does that.
        mock_to_thread = AsyncMock(return_value=FAKE_EMBEDDING)

        mock_settings = MagicMock()
        mock_settings.use_mock_api = False   # real embedding path
        mock_settings.gemini_api_key = "fake-key"

        mock_sum_svc = MagicMock()
        mock_sum_svc.summarize = AsyncMock()
        mock_get_sum = MagicMock(return_value=mock_sum_svc)

        mock_pc = MagicMock()
        mock_pc.upsert_vectors = MagicMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = MagicMock(return_value=cm)

        from app.services.indexing_pipeline import run_pipeline  # noqa: PLC0415

        with (
            patch(f"{PIPELINE_MOD}.asyncio.to_thread", mock_to_thread),
            patch(f"{PIPELINE_MOD}.get_settings", return_value=mock_settings),
            patch(
                f"{PIPELINE_MOD}.get_semantic_scholar_service",
                return_value=MagicMock(
                    get_paper_details=AsyncMock(return_value=paper)
                ),
            ),
            patch(f"{PIPELINE_MOD}.get_pinecone_client", return_value=mock_pc),
            patch(
                "app.services.summarization_service.get_summarization_service",
                new=mock_get_sum,
            ),
            patch("app.db.engine.AsyncSessionLocal", new=mock_session_factory),
        ):
            await run_pipeline(PAPER_ID)

        # Every to_thread call in the embedding path must use _embed_single
        # as the first positional argument.
        embed_calls = [
            c for c in mock_to_thread.call_args_list
            if c.args and c.args[0] is _embed_single
        ]

        assert len(embed_calls) >= 1, (
            "asyncio.to_thread(_embed_single, ...) was never called — "
            "_embed_single is running synchronously on the event loop."
        )

        # Every call must pass exactly one chunk string as the second argument.
        for c in embed_calls:
            chunk_arg = c.args[1]
            assert isinstance(chunk_arg, str) and chunk_arg, (
                f"Expected a non-empty str chunk, got {chunk_arg!r}"
            )

        # The pipeline must have completed (not FAILED) when embedding succeeds.
        assert pipeline_state.pipeline_status.get(PAPER_ID) == PipelineStatus.COMPLETE, (
            f"Expected COMPLETE, got {pipeline_state.pipeline_status.get(PAPER_ID)}. "
            f"Message: {pipeline_state.pipeline_messages.get(PAPER_ID)}"
        )

    async def test_embed_not_threaded_in_mock_mode(self):
        """
        In mock mode, embeddings are zero-vectors generated locally — no
        asyncio.to_thread(_embed_single) call should be made.
        """
        from app.services.indexing_pipeline import _embed_single, run_pipeline  # noqa: PLC0415

        paper = self._make_paper(abstract="Short abstract. " * 20)
        mock_to_thread = AsyncMock(return_value=FAKE_EMBEDDING)

        mock_settings = MagicMock()
        mock_settings.use_mock_api = True   # mock path — no real Gemini
        mock_settings.gemini_api_key = None

        mock_sum_svc = MagicMock()
        mock_sum_svc.summarize = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(f"{PIPELINE_MOD}.asyncio.to_thread", mock_to_thread),
            patch(f"{PIPELINE_MOD}.get_settings", return_value=mock_settings),
            patch(
                f"{PIPELINE_MOD}.get_semantic_scholar_service",
                return_value=MagicMock(
                    get_paper_details=AsyncMock(return_value=paper)
                ),
            ),
            patch(f"{PIPELINE_MOD}.get_pinecone_client", return_value=MagicMock()),
            patch(
                "app.services.summarization_service.get_summarization_service",
                new=MagicMock(return_value=mock_sum_svc),
            ),
            patch("app.db.engine.AsyncSessionLocal", new=MagicMock(return_value=cm)),
        ):
            await run_pipeline(PAPER_ID)

        embed_calls = [
            c for c in mock_to_thread.call_args_list
            if c.args and c.args[0] is _embed_single
        ]
        assert len(embed_calls) == 0, (
            "asyncio.to_thread(_embed_single) must NOT be called in mock mode."
        )


# ===========================================================================
# 3.  Frontend config — static source analysis of frontend/lib/api.ts
# ===========================================================================


class TestFrontendApiBaseConfig:
    """
    Parse frontend/lib/api.ts as text and assert the correct env-var pattern
    and fallback are present.  No JS runtime required.
    """

    @staticmethod
    def _api_ts_source() -> str:
        root = pathlib.Path(__file__).parent.parent.parent  # repo root
        api_ts = root / "frontend" / "lib" / "api.ts"
        assert api_ts.exists(), f"Expected {api_ts} to exist"
        return api_ts.read_text()

    def test_next_public_api_url_env_var_is_used(self):
        """BASE must reference process.env.NEXT_PUBLIC_API_URL."""
        src = self._api_ts_source()
        assert "process.env.NEXT_PUBLIC_API_URL" in src, (
            "frontend/lib/api.ts does not read process.env.NEXT_PUBLIC_API_URL — "
            "the API base URL is not environment-configurable."
        )

    def test_localhost_fallback_is_present(self):
        """The hardcoded localhost fallback must still exist for local dev."""
        src = self._api_ts_source()
        assert "http://localhost:8000/api/v1" in src, (
            "The localhost:8000 fallback is missing from frontend/lib/api.ts."
        )

    def test_nullish_coalescing_operator_used_for_fallback(self):
        """?? (nullish coalescing) should wire the env var to the fallback."""
        src = self._api_ts_source()
        assert "??" in src, (
            "frontend/lib/api.ts does not use the ?? operator — "
            "env var and fallback may not be wired together correctly."
        )

    def test_env_var_appears_before_fallback(self):
        """Env var must take precedence: it must appear before the fallback literal."""
        src = self._api_ts_source()
        env_pos = src.find("NEXT_PUBLIC_API_URL")
        fallback_pos = src.find("http://localhost:8000/api/v1")
        assert env_pos < fallback_pos, (
            "NEXT_PUBLIC_API_URL must appear before the fallback URL in api.ts "
            "to ensure the env var takes precedence."
        )

    def test_base_const_assignment_is_single_line_or_multiline(self):
        """BASE must be assigned on the same logical statement as the env var."""
        src = self._api_ts_source()
        # Match: const BASE = <anything containing NEXT_PUBLIC_API_URL>
        # across one or two lines (multiline assignment is fine).
        pattern = re.compile(
            r"const\s+BASE\s*=\s*[\s\S]{0,200}?NEXT_PUBLIC_API_URL",
            re.MULTILINE,
        )
        assert pattern.search(src), (
            "Could not find 'const BASE = ... NEXT_PUBLIC_API_URL ...' in api.ts. "
            "BASE may not be reading the environment variable."
        )
