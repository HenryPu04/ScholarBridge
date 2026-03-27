import asyncio
import logging
import time

import httpx

from app.config import get_settings
from app.models.paper import Author, OpenAccessPdf, PaperDetail, PaperResult

logger = logging.getLogger(__name__)


class SemanticScholarError(Exception):
    """Raised when the Semantic Scholar API fails after all retries."""


class SemanticScholarService:
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    SEARCH_FIELDS = (
        "paperId,title,abstract,authors,year,citationCount,"
        "fieldsOfStudy,openAccessPdf,venue,externalIds"
    )
    DETAIL_FIELDS = (
        "paperId,title,abstract,authors,year,citationCount,"
        "fieldsOfStudy,openAccessPdf,venue,externalIds,"
        "tldr,referenceCount,influentialCitationCount"
    )

    def __init__(self) -> None:
        settings = get_settings()
        headers: dict[str, str] = {
            "User-Agent": "ScholarBridge/0.1 (research-to-nonprofits platform)"
        }
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
            # Authenticated: 1 req/s → allow up to 5 concurrent with tight spacing
            self._semaphore = asyncio.Semaphore(5)
            self._request_delay = 0.2  # seconds between requests per slot
            masked = f"{'*' * 8}{settings.semantic_scholar_api_key[-4:]}"
            logger.info("SemanticScholarService: x-api-key present (…%s), authenticated rate limit active.", masked)
        else:
            # Unauthenticated: ~100 req/5min → be conservative
            self._semaphore = asyncio.Semaphore(1)
            self._request_delay = 2.0
            logger.warning("SemanticScholarService: no x-api-key found — using unauthenticated rate limit (slow).")

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers=headers,
        )
        # Cache stores (value, timestamp) tuples keyed by a string cache key.
        self._cache: dict[str, tuple[object, float]] = {}
        self._cache_ttl = 300  # seconds

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> object | None:
        if key in self._cache:
            value, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return value
            del self._cache[key]
        return None

    def _cache_set(self, key: str, value: object) -> None:
        self._cache[key] = (value, time.time())

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict) -> dict:
        """Throttled GET with exponential backoff on 429. Always raises on failure."""
        max_retries = 3
        last_exc: Exception | None = None

        async with self._semaphore:
            await asyncio.sleep(self._request_delay)
            for attempt in range(max_retries + 1):
                try:
                    response = await self._client.get(path, params=params)

                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", "10"))
                        logger.warning(
                            "Semantic Scholar rate limited on %s (attempt %d/%d). "
                            "Waiting %ss. Key present: %s",
                            path, attempt + 1, max_retries + 1, retry_after,
                            "x-api-key" in self._client.headers,
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response.json()

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Semantic Scholar HTTP %s on %s (attempt %d/%d).",
                        exc.response.status_code, path, attempt + 1, max_retries + 1,
                    )
                    last_exc = exc
                    if exc.response.status_code not in (429, 500, 502, 503):
                        # Non-retryable (e.g. 404) — fail immediately
                        raise SemanticScholarError(
                            f"Semantic Scholar returned {exc.response.status_code} for {path}"
                        ) from exc
                except httpx.RequestError as exc:
                    logger.error(
                        "Semantic Scholar request error on %s (attempt %d/%d): %s",
                        path, attempt + 1, max_retries + 1, exc,
                    )
                    last_exc = exc

                if attempt < max_retries:
                    backoff = self._request_delay * (2 ** attempt)
                    await asyncio.sleep(backoff)

        raise SemanticScholarError(
            f"Semantic Scholar failed after {max_retries + 1} attempts for {path}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
        open_access_only: bool = False,
    ) -> list[PaperResult]:
        cache_key = f"search:{query}:{limit}:{year_min}:{year_max}:{open_access_only}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params: dict[str, object] = {
            "query": query,
            "limit": limit,
            "fields": self.SEARCH_FIELDS,
        }
        if year_min or year_max:
            lo = year_min or 1900
            hi = year_max or 2100
            params["year"] = f"{lo}-{hi}"
        if open_access_only:
            # Semantic Scholar uses the presence of this param as a boolean
            # filter; an empty string signals "only open-access papers".
            params["openAccessPdf"] = ""

        data = await self._get("/paper/search", params)
        papers: list[PaperResult] = [
            self._map_paper_result(p) for p in data.get("data", [])
        ]
        self._cache_set(cache_key, papers)
        return papers

    async def get_paper_details(self, paper_id: str) -> PaperDetail:
        cache_key = f"detail:{paper_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        data = await self._get(f"/paper/{paper_id}", {"fields": self.DETAIL_FIELDS})
        detail = self._map_paper_detail(data)
        self._cache_set(cache_key, detail)
        return detail

    async def get_paper_pdf_url(self, paper_id: str) -> str | None:
        """Return the open-access PDF URL for a paper, or None if unavailable."""
        detail = await self.get_paper_details(paper_id)
        if detail.open_access_pdf:
            return detail.open_access_pdf.url
        return None

    async def search_authors(self, name: str, limit: int = 5) -> list[dict]:
        """Search for researchers by name — used in the researcher claiming flow (Phase 4)."""
        cache_key = f"author_search:{name}:{limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params: dict[str, object] = {
            "query": name,
            "limit": limit,
            "fields": "authorId,name,affiliations,homepage,paperCount,citationCount",
        }
        data = await self._get("/author/search", params)
        results: list[dict] = data.get("data", [])
        self._cache_set(cache_key, results)
        return results

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _map_paper_result(self, data: dict | None) -> PaperResult:
        if not data or not isinstance(data, dict):
            raise SemanticScholarError(
                f"Unexpected response shape from Semantic Scholar: {type(data)!r}"
            )
        authors = [
            Author(author_id=a.get("authorId"), name=a.get("name", "Unknown"))
            for a in (data.get("authors") or [])
        ]
        oap = data.get("openAccessPdf")
        open_access_pdf = (
            OpenAccessPdf(url=oap["url"], status=oap.get("status", "UNKNOWN"))
            if oap and oap.get("url")
            else None
        )
        return PaperResult(
            paper_id=data.get("paperId", ""),
            title=data.get("title", "Untitled"),
            abstract=data.get("abstract"),
            authors=authors,
            year=data.get("year"),
            citation_count=data.get("citationCount"),
            fields_of_study=data.get("fieldsOfStudy") or [],
            open_access_pdf=open_access_pdf,
            venue=data.get("venue"),
            external_ids=data.get("externalIds"),
        )

    def _map_paper_detail(self, data: dict | None) -> PaperDetail:
        if not data or not isinstance(data, dict):
            raise SemanticScholarError(
                f"Unexpected response shape from Semantic Scholar: {type(data)!r}"
            )
        base = self._map_paper_result(data)
        tldr_obj = data.get("tldr")
        return PaperDetail(
            **base.model_dump(),
            tldr=tldr_obj.get("text") if isinstance(tldr_obj, dict) else None,
            reference_count=data.get("referenceCount"),
            influential_citation_count=data.get("influentialCitationCount"),
        )


# ---------------------------------------------------------------------------
# Module-level singleton — instantiated once, shared across all requests.
# ---------------------------------------------------------------------------

_service_instance: SemanticScholarService | None = None


def get_semantic_scholar_service() -> SemanticScholarService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SemanticScholarService()
    return _service_instance
