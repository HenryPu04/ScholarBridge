"""
Mock Semantic Scholar service for local development.

Used when USE_MOCK_API=true in .env so the JIT indexing pipeline
(PDF download → chunk → embed → Pinecone upsert) can be built and
tested without a real Semantic Scholar API key.

Fixture coverage
----------------
- "cover crops"  → 3 results; paper_1 has an open-access PDF
- "soil health"  → 3 results; paper_4 has an open-access PDF
- "regenerative" → 1 result;  abstract-only (no PDF) — tests fallback path
- Any other query → empty list (tests zero-results UI state)

Paper IDs for direct detail lookups
------------------------------------
  MOCK_COVER_001  open-access PDF
  MOCK_COVER_002  abstract only
  MOCK_COVER_003  abstract only
  MOCK_SOIL_001   open-access PDF
  MOCK_SOIL_002   abstract only
  MOCK_SOIL_003   abstract only
  MOCK_REGEN_001  abstract only

PDF URL note
------------
MOCK_COVER_001 and MOCK_SOIL_001 point to real, publicly accessible
PDFs so the Step 1.3 pipeline can exercise the full download path.
If either URL goes offline, swap it for any reachable PDF.
"""

import logging
from app.models.paper import Author, OpenAccessPdf, PaperDetail, PaperResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_AUTHORS = {
    "lundberg": Author(author_id="MOCK_A001", name="Sara Lundberg"),
    "pierce":   Author(author_id="MOCK_A002", name="Frederick Pierce"),
    "osei":     Author(author_id="MOCK_A003", name="Abena Osei"),
    "tanaka":   Author(author_id="MOCK_A004", name="Hiroshi Tanaka"),
    "mbeki":    Author(author_id="MOCK_A005", name="Nomvula Mbeki"),
    "chen":     Author(author_id="MOCK_A006", name="Wei Chen"),
    "diallo":   Author(author_id="MOCK_A007", name="Fatou Diallo"),
}

# A real open-access FAO technical paper on soil & cover crops.
# Large enough (~80 pages) to stress-test the chunking logic.
_FAO_SOILS_PDF = OpenAccessPdf(
    url="https://www.fao.org/3/i9548en/i9548en.pdf",
    status="GOLD",
)

# A real open-access paper on conservation agriculture from CGIAR.
_CGIAR_COVER_PDF = OpenAccessPdf(
    url="https://cgspace.cgiar.org/bitstream/handle/10568/97862/cover_crops_guide.pdf",
    status="GREEN",
)

_FIXTURES: dict[str, PaperDetail] = {
    # ------------------------------------------------------------------
    # Cover crops cluster
    # ------------------------------------------------------------------
    "MOCK_COVER_001": PaperDetail(
        paper_id="MOCK_COVER_001",
        title="Cover Crops as a Tool for Nitrogen Management and Weed Suppression in Smallholder Farms",
        abstract=(
            "Cover crops have long been recognized for their ability to fix atmospheric "
            "nitrogen and suppress weed growth. This study evaluated twelve cover crop "
            "species across 45 smallholder plots in sub-Saharan Africa over three seasons. "
            "Leguminous species (Mucuna pruriens, Lablab purpureus) reduced synthetic "
            "fertilizer requirements by 38% on average and cut weed biomass by 52%. "
            "Cruciferous species showed strong allelopathic effects but poor nitrogen "
            "contributions. Results indicate that integrating a legume-cereal cover crop "
            "mix reduces input costs by approximately $120 per hectare per season while "
            "maintaining comparable yields to conventional management."
        ),
        authors=[_AUTHORS["lundberg"], _AUTHORS["pierce"]],
        year=2022,
        citation_count=87,
        fields_of_study=["Agricultural Science", "Environmental Science"],
        open_access_pdf=_FAO_SOILS_PDF,
        venue="Field Crops Research",
        tldr=(
            "Leguminous cover crops reduce fertilizer costs by 38% and weed biomass "
            "by 52% on smallholder farms in sub-Saharan Africa."
        ),
        reference_count=54,
        influential_citation_count=12,
    ),
    "MOCK_COVER_002": PaperDetail(
        paper_id="MOCK_COVER_002",
        title="Winter Cover Crop Selection for Carbon Sequestration in Temperate Dryland Systems",
        abstract=(
            "Selecting appropriate cover crops for carbon sequestration in dryland "
            "temperate systems requires balancing biomass production with water use. "
            "This meta-analysis of 23 long-term trials across North America found that "
            "cereal rye (Secale cereale) consistently outperformed other species in "
            "biomass production per millimeter of water used. Soil organic carbon "
            "increased by 0.18% annually in plots with continuous winter cover cropping "
            "compared to 0.03% in fallow controls. Farmer interviews highlighted "
            "termination timing and equipment access as the primary adoption barriers."
        ),
        authors=[_AUTHORS["osei"], _AUTHORS["tanaka"]],
        year=2021,
        citation_count=43,
        fields_of_study=["Agricultural Science", "Climate Science"],
        open_access_pdf=None,  # abstract-only fallback path
        venue="Agriculture, Ecosystems & Environment",
        tldr="Cereal rye is optimal for carbon sequestration in dryland systems.",
        reference_count=38,
        influential_citation_count=6,
    ),
    "MOCK_COVER_003": PaperDetail(
        paper_id="MOCK_COVER_003",
        title="Farmer Adoption of Cover Crops: Barriers, Incentives, and Extension Strategies",
        abstract=(
            "Despite documented agronomic benefits, cover crop adoption rates remain "
            "below 15% among smallholder farmers in most developing regions. "
            "Semi-structured interviews with 312 farmers across Kenya, Ghana, and "
            "Zambia identified seed cost (cited by 71%), lack of extension support "
            "(63%), and uncertainty about drought years (58%) as primary barriers. "
            "Subsidized seed programs combined with farmer field school models "
            "increased adoption intent by 44 percentage points in pilot districts. "
            "Policy implications for national agricultural extension services are discussed."
        ),
        authors=[_AUTHORS["mbeki"], _AUTHORS["diallo"]],
        year=2023,
        citation_count=19,
        fields_of_study=["Agricultural Science", "Sociology"],
        open_access_pdf=None,
        venue="World Development",
        tldr="Subsidized seeds + field schools increase cover crop adoption intent by 44pp.",
        reference_count=67,
        influential_citation_count=4,
    ),
    # ------------------------------------------------------------------
    # Soil health cluster
    # ------------------------------------------------------------------
    "MOCK_SOIL_001": PaperDetail(
        paper_id="MOCK_SOIL_001",
        title="Measuring Soil Health: A Practical Framework for Non-Laboratory Assessment on Smallholder Farms",
        abstract=(
            "Laboratory-based soil health assessments are cost-prohibitive for most "
            "smallholder farmers. This paper presents a validated field-based scoring "
            "system using six low-cost indicators: earthworm count, aggregate stability, "
            "infiltration rate, surface cover percentage, crop residue decomposition, "
            "and organic matter color comparison. The framework was validated against "
            "laboratory results from 890 plots across 7 countries (r=0.81). A step-by-step "
            "farmer training protocol enabled community health workers with no laboratory "
            "access to reliably classify soils as degraded, recovering, or healthy. "
            "The tool is designed to be completed in under 45 minutes per plot."
        ),
        authors=[_AUTHORS["chen"], _AUTHORS["osei"]],
        year=2022,
        citation_count=134,
        fields_of_study=["Soil Science", "Agricultural Science"],
        open_access_pdf=_CGIAR_COVER_PDF,
        venue="Soil and Tillage Research",
        tldr=(
            "A 6-indicator field tool lets farmers assess soil health in under 45 minutes "
            "with 81% correlation to lab results."
        ),
        reference_count=72,
        influential_citation_count=21,
    ),
    "MOCK_SOIL_002": PaperDetail(
        paper_id="MOCK_SOIL_002",
        title="Microbial Biomass Carbon as an Early Indicator of Soil Health Degradation Under Continuous Cultivation",
        abstract=(
            "Microbial biomass carbon (MBC) responds more rapidly to management changes "
            "than total organic carbon, making it a sensitive early-warning indicator "
            "for soil degradation. Longitudinal data from 16-year continuous cultivation "
            "trials in South Asia showed MBC declined by 34% within the first four years "
            "of continuous rice-wheat systems, preceding detectable drops in total organic "
            "carbon by 2-3 seasons. Incorporation of crop residues and reduced tillage "
            "stabilized MBC at baseline levels. Findings support MBC monitoring as a "
            "cost-effective leading indicator for soil health programs targeting "
            "early intervention before irreversible degradation."
        ),
        authors=[_AUTHORS["tanaka"], _AUTHORS["lundberg"]],
        year=2020,
        citation_count=211,
        fields_of_study=["Soil Science", "Microbiology"],
        open_access_pdf=None,
        venue="Soil Biology and Biochemistry",
        tldr="Microbial biomass carbon predicts soil degradation 2-3 seasons earlier than TOC.",
        reference_count=89,
        influential_citation_count=38,
    ),
    "MOCK_SOIL_003": PaperDetail(
        paper_id="MOCK_SOIL_003",
        title="Drought Resilience Through Improved Soil Health: Evidence from Dryland Farming Communities",
        abstract=(
            "Farms with higher soil organic matter content demonstrate significantly "
            "greater yield stability under drought conditions. Analysis of 7-year panel "
            "data from 1,200 smallholder farms in the Sahel found that a 1% increase in "
            "soil organic matter was associated with a 12% reduction in yield variance "
            "during drought years. Practices contributing most to organic matter gains "
            "included minimal tillage (contributing 41% of gains), residue retention "
            "(33%), and legume integration (26%). These results suggest soil health "
            "investment has dual returns: baseline productivity improvement and "
            "climate shock buffer, making it particularly relevant for food security programming."
        ),
        authors=[_AUTHORS["diallo"], _AUTHORS["mbeki"], _AUTHORS["pierce"]],
        year=2023,
        citation_count=56,
        fields_of_study=["Agricultural Science", "Climate Science", "Food Security"],
        open_access_pdf=None,
        venue="Nature Food",
        tldr="1% more soil organic matter → 12% less yield variance in drought years.",
        reference_count=91,
        influential_citation_count=14,
    ),
    # ------------------------------------------------------------------
    # Regenerative agriculture cluster (abstract-only — tests fallback)
    # ------------------------------------------------------------------
    "MOCK_REGEN_001": PaperDetail(
        paper_id="MOCK_REGEN_001",
        title="Defining Regenerative Agriculture: A Systematic Review of Principles and Outcomes",
        abstract=(
            "The term 'regenerative agriculture' lacks a standardized definition, creating "
            "challenges for policy adoption and impact measurement. This systematic review "
            "analyzed 187 peer-reviewed articles published between 2010 and 2023 to identify "
            "core principles. Five principles appeared in over 70% of definitions: minimizing "
            "soil disturbance, maximizing soil cover, diversifying plant communities, "
            "integrating livestock, and eliminating synthetic inputs. However, outcomes "
            "reported varied substantially: yield impacts ranged from -22% to +31% relative "
            "to conventional systems, depending on transition stage, agroecological zone, "
            "and baseline soil health. This review proposes a tiered outcome framework "
            "to help practitioners set realistic expectations during the 3-5 year transition period."
        ),
        authors=[_AUTHORS["chen"], _AUTHORS["diallo"], _AUTHORS["osei"]],
        year=2023,
        citation_count=29,
        fields_of_study=["Agricultural Science", "Environmental Science"],
        open_access_pdf=None,
        venue="Global Food Security",
        tldr="Regenerative ag yields range from -22% to +31%; a tiered outcome framework helps practitioners set expectations.",
        reference_count=187,
        influential_citation_count=7,
    ),
}

# Search index: maps lowercase query keywords to lists of paper IDs
_SEARCH_INDEX: dict[str, list[str]] = {
    "cover crop":     ["MOCK_COVER_001", "MOCK_COVER_002", "MOCK_COVER_003"],
    "cover crops":    ["MOCK_COVER_001", "MOCK_COVER_002", "MOCK_COVER_003"],
    "soil health":    ["MOCK_SOIL_001",  "MOCK_SOIL_002",  "MOCK_SOIL_003"],
    "soil":           ["MOCK_SOIL_001",  "MOCK_SOIL_002",  "MOCK_SOIL_003"],
    "drought":        ["MOCK_SOIL_003",  "MOCK_COVER_002"],
    "nitrogen":       ["MOCK_COVER_001"],
    "carbon":         ["MOCK_COVER_002", "MOCK_SOIL_002"],
    "microbial":      ["MOCK_SOIL_002"],
    "regenerative":   ["MOCK_REGEN_001"],
    "adoption":       ["MOCK_COVER_003"],
    "smallholder":    ["MOCK_COVER_001", "MOCK_SOIL_001", "MOCK_SOIL_003"],
}


def _match_query(query: str) -> list[str]:
    """Return paper IDs for the first keyword in the index that appears in the query."""
    q = query.lower()
    for keyword, ids in _SEARCH_INDEX.items():
        if keyword in q:
            return ids
    return []


# ---------------------------------------------------------------------------
# Mock service — identical interface to SemanticScholarService
# ---------------------------------------------------------------------------

class MockSemanticScholarService:
    """Drop-in replacement for SemanticScholarService during local dev."""

    async def close(self) -> None:
        pass

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
        open_access_only: bool = False,
    ) -> list[PaperResult]:
        logger.info("[MOCK] search_papers query=%r", query)
        ids = _match_query(query)[:limit]
        results: list[PaperResult] = []
        for pid in ids:
            detail = _FIXTURES.get(pid)
            if detail is None:
                continue
            if year_min and detail.year and detail.year < year_min:
                continue
            if year_max and detail.year and detail.year > year_max:
                continue
            if open_access_only and detail.open_access_pdf is None:
                continue
            results.append(PaperResult(**detail.model_dump()))
        return results

    async def get_paper_details(self, paper_id: str) -> PaperDetail:
        logger.info("[MOCK] get_paper_details paper_id=%r", paper_id)
        detail = _FIXTURES.get(paper_id)
        if detail is None:
            # Mimic the httpx.HTTPStatusError a real 404 would raise.
            # The router catches this and returns a proper 404 response.
            import httpx
            raise httpx.HTTPStatusError(
                message=f"Mock: paper '{paper_id}' not found",
                request=httpx.Request("GET", f"/paper/{paper_id}"),
                response=httpx.Response(404),
            )
        return detail

    async def get_paper_pdf_url(self, paper_id: str) -> str | None:
        detail = _FIXTURES.get(paper_id)
        if detail and detail.open_access_pdf:
            return detail.open_access_pdf.url
        return None

    async def search_authors(self, name: str, limit: int = 5) -> list[dict]:
        logger.info("[MOCK] search_authors name=%r", name)
        return [
            {
                "authorId": "MOCK_A001",
                "name": "Sara Lundberg",
                "affiliations": ["Wageningen University"],
                "homepage": None,
                "paperCount": 34,
                "citationCount": 891,
            }
        ]


# ---------------------------------------------------------------------------
# Singleton factory — mirrors get_semantic_scholar_service()
# ---------------------------------------------------------------------------

_mock_instance: MockSemanticScholarService | None = None


def get_mock_semantic_scholar_service() -> MockSemanticScholarService:
    global _mock_instance
    if _mock_instance is None:
        _mock_instance = MockSemanticScholarService()
    return _mock_instance
