"""Typed, UI-compatible contracts for the Breadcrumbs MCP surface."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import models_json_schema

FindingStatus = Literal["confirmed", "in_progress", "abandoned"]
StorageStatus = Literal["confirmed", "in-progress", "abandoned", "open"]
Relationship = Literal["duplicate_of", "extends", "related", "contradicts"]
DuplicationVerdict = Literal["match", "open"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Match(ContractModel):
    id: str
    status: FindingStatus
    relationship: Literal["duplicate_of", "extends", "related"]
    hypothesis_text: str
    effect: str
    reason: str | None
    author: str
    disease: str


class CheckDuplicationInput(ContractModel):
    hypothesis_text: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class DuplicationResult(ContractModel):
    verdict: DuplicationVerdict
    matches: list[Match]
    searched: int = Field(ge=0)
    markdown: str | None = None


class Resource(ContractModel):
    type: Literal["paper", "database"]
    citation: str = Field(min_length=1)
    url: str | None = None


class WriteFindingInput(ContractModel):
    id: str | None = None
    category: str
    disease: str
    hypothesis_text: str
    entities: list[str]
    effect: str
    status: StorageStatus
    author: str
    source_session_id: str
    source_type: Literal["internal", "external"]
    created_at: str | None = None
    signature: str | None = None
    n: int | None = None
    provenance: str | None = None
    reason: str | None = None
    note: str | None = None
    markdown: str | None = None
    resources: list[Resource] | None = None


class RecallFindingsInput(ContractModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class FindingRelationship(ContractModel):
    finding_id: str
    relationship: Relationship


class RecallFinding(ContractModel):
    id: str
    disease: str
    hypothesis_text: str
    signature: str | None = None
    effect: str | None = None
    n: int | None = None
    status: StorageStatus
    author: str
    timestamp: str
    provenance: str | None = None
    reason: str | None = None
    note: str | None = None
    category: str | None = None
    entities: list[str]
    source_session_id: str | None = None
    source_type: Literal["internal", "external"] | None = None
    markdown: str | None = None
    resources: list[Resource]
    relationships: list[FindingRelationship] = Field(default_factory=list)
    score: float = Field(ge=0)


class RecallFindingsResult(ContractModel):
    query: str
    findings: list[RecallFinding]
    searched: int = Field(ge=0)
    sources_searched: list[str]


class RenderWikiInput(ContractModel):
    finding_ids: list[str] | None = None
    title: str = "Breadcrumbs research memory"


class RenderWikiResult(ContractModel):
    markdown: str
    finding_ids: list[str]


CONTRACT_MODELS = (
    CheckDuplicationInput,
    DuplicationResult,
    WriteFindingInput,
    RecallFindingsInput,
    RecallFindingsResult,
    RenderWikiInput,
    RenderWikiResult,
)


def contract_schema() -> dict:
    """Return one checked schema bundle for every public MCP model."""

    _, schema = models_json_schema(
        [(model, "validation") for model in CONTRACT_MODELS],
        title="Breadcrumbs MCP contracts",
    )
    return schema


def write_contract_schema(path: str | Path) -> Path:
    import json

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contract_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
