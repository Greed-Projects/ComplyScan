from typing import Literal

from pydantic import BaseModel, Field


Status = Literal["pass", "warning", "fail", "not_applicable"]
Applicability = Literal["required", "not_applicable"]
PackageForm = Literal["single", "combination", "group", "multi_piece"]
CommodityClass = Literal["general", "tobacco", "pan_masala"]
InputMode = Literal["images", "manual_text"]


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class OcrRegion(BaseModel):
    id: str
    text: str
    confidence: float = Field(ge=0, le=1)
    polygon: list[Point]
    bbox: list[float] = Field(min_length=4, max_length=4)
    source: str = "primary"
    source_image_id: str | None = None


class ImageMetadata(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PackageContext(BaseModel):
    imported_product: bool = False
    may_become_unfit_for_human_consumption: bool = False
    dimensions_relevant: bool = False
    package_form: PackageForm = "single"
    alcoholic_beverage: bool = False
    commodity_class: CommodityClass = "general"


class RuleProfileMetadata(BaseModel):
    id: str
    title: str
    jurisdiction: str
    legal_basis: str
    checked_through: str
    scope: str
    exclusions: list[str] = Field(default_factory=list)


class ExtractedDeclaration(BaseModel):
    key: str
    label: str
    value: str
    evidence: str
    confidence: float = Field(ge=0, le=1)
    attributes: dict[str, str] = Field(default_factory=dict)
    region_ids: list[str] = Field(default_factory=list)
    source_image_ids: list[str] = Field(default_factory=list)


class DeclarationCheck(BaseModel):
    rule_id: str
    key: str
    label: str
    legal_reference: str
    requirement: str
    applicability: Applicability
    status: Status
    value: str | None = None
    evidence: str | None = None
    confidence: float = Field(ge=0, le=1)
    message: str
    region_ids: list[str] = Field(default_factory=list)
    source_image_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


class OcrVariantTrace(BaseModel):
    crop: str
    variant: str
    family: str
    text: str | None = None
    parsed_value: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class OcrRecoveryTrace(BaseModel):
    declaration_key: str
    locator: str
    reference_evidence: str
    attempted: bool
    resolved: bool
    attempts: int = 0
    strategy: str | None = None
    recovered_text: str | None = None
    region_ids: list[str] = Field(default_factory=list)
    variants: list[OcrVariantTrace] = Field(default_factory=list)
    message: str
    source_image_id: str | None = None


class ComplianceSummary(BaseModel):
    score: int | None = Field(default=None, ge=0, le=100)
    status: Status
    passed: int
    warnings: int
    failed: int
    not_applicable: int = 0


class PackageImageAnalysis(BaseModel):
    image_id: str
    file_name: str
    ocr_engine: str
    ocr_text: str
    image: ImageMetadata
    regions: list[OcrRegion] = Field(default_factory=list)
    ocr_recovery: list[OcrRecoveryTrace] = Field(default_factory=list)
    declarations: list[ExtractedDeclaration] = Field(default_factory=list)


class FusionImageEvidence(BaseModel):
    image_id: str
    file_name: str
    ocr_text: str
    declarations: list[ExtractedDeclaration] = Field(default_factory=list)


class FusionRequest(BaseModel):
    images: list[FusionImageEvidence] = Field(min_length=1, max_length=6)
    context: PackageContext


class AnalysisResponse(BaseModel):
    input_mode: InputMode
    file_names: list[str] = Field(default_factory=list)
    image_count: int = Field(ge=0)
    images: list[PackageImageAnalysis] = Field(default_factory=list)
    ocr_text: str
    declarations: list[ExtractedDeclaration] = Field(default_factory=list)
    context: PackageContext
    ruleset: str
    rule_profile: RuleProfileMetadata
    summary: ComplianceSummary
    checks: list[DeclarationCheck]
    disclaimer: str
