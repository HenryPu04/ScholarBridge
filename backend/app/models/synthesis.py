from pydantic import BaseModel, field_validator


class SynthesisRequest(BaseModel):
    paper_ids: list[str]

    @field_validator("paper_ids")
    @classmethod
    def check_count(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("Minimum 2 papers required for synthesis.")
        if len(v) > 5:
            raise ValueError("Maximum 5 papers allowed per synthesis.")
        return v


class SynthesisResult(BaseModel):
    paper_ids: list[str]
    consensus_findings: list[str]
    conflicting_evidence: list[str]
    combined_recommendation: str
    evidence_strength: str
    created_at: str   # ISO 8601 timestamp
    cached: bool      # True if returned from DB cache within TTL
