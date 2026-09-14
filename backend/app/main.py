from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import analyze_text_with_declarations
from .extraction import extract_declarations
from .inspection import merge_image_declarations
from .legal_profiles import PROFILE
from .models import (
    AnalysisResponse,
    CommodityClass,
    ExtractedDeclaration,
    ImageMetadata,
    OcrRecoveryTrace,
    OcrRegion,
    PackageContext,
    PackageForm,
    PackageImageAnalysis,
    Point,
)
from .ocr import get_ocr_engine
from .ocr.targeted_recovery import recover_referenced_declarations
from .rules import RULESET_ID, evaluate_declarations

app = FastAPI(
    title="PackCheck AI Prototype API",
    description="SIH 2026 / Problem Statement 26034 prototype",
    version="0.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCLAIMER = (
    "Prototype screening only, not a legal determination. The active rule profile covers selected declarations on "
    "physical retail packages and intentionally excludes unresolved specialized regimes, font/PDP geometry, measurement "
    "verification and e-commerce listing-only obligations. Enforcement decisions require the applicable current law and human review."
)

MAX_IMAGES = 6
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REQUEST_IMAGE_BYTES = 40 * 1024 * 1024


def _api_region(region, image_id: str | None = None) -> OcrRegion:
    region_id = f"{image_id}:{region.id}" if image_id else region.id
    return OcrRegion(
        id=region_id,
        text=region.text,
        confidence=region.confidence,
        polygon=[Point(x=x, y=y) for x, y in region.polygon],
        bbox=list(region.bbox),
        source=region.source,
        source_image_id=image_id,
    )


def _namespace_declaration(
    declaration: ExtractedDeclaration,
    image_id: str,
    file_name: str,
) -> ExtractedDeclaration:
    attributes = dict(declaration.attributes)
    attributes["source_file"] = file_name
    return declaration.model_copy(
        update={
            "attributes": attributes,
            "region_ids": [f"{image_id}:{region_id}" for region_id in declaration.region_ids],
            "source_image_ids": [image_id],
        }
    )


def _namespace_trace(trace: OcrRecoveryTrace, image_id: str) -> OcrRecoveryTrace:
    return trace.model_copy(
        update={
            "region_ids": [f"{image_id}:{region_id}" for region_id in trace.region_ids],
            "source_image_id": image_id,
        }
    )


def _combined_ocr_text(images: list[PackageImageAnalysis]) -> str:
    sections = [
        f"--- {image.file_name} ---\n{image.ocr_text.strip()}"
        for image in images
        if image.ocr_text.strip()
    ]
    return "\n\n".join(sections).strip()


def _analyze_image(
    raw: bytes,
    file_name: str,
    image_id: str,
    context: PackageContext,
    engine,
) -> PackageImageAnalysis:
    ocr = engine.extract(raw)
    local_regions = [_api_region(region) for region in ocr.regions]
    ocr_text = ocr.text

    direct_declarations = extract_declarations(ocr_text, local_regions)
    recovery = recover_referenced_declarations(
        raw,
        ocr_text,
        direct_declarations,
        engine,
        primary_regions=ocr.regions,
    )
    if recovery.regions:
        local_regions.extend(_api_region(region) for region in recovery.regions)
    if recovery.recovered_text:
        ocr_text = "\n".join([ocr_text, *recovery.recovered_text]).strip()

    declarations, _, _ = analyze_text_with_declarations(
        ocr_text,
        local_regions,
        context,
        supplemental_declarations=recovery.declarations,
    )

    namespaced_regions = [
        region.model_copy(
            update={
                "id": f"{image_id}:{region.id}",
                "source_image_id": image_id,
            }
        )
        for region in local_regions
    ]
    namespaced_declarations = [
        _namespace_declaration(declaration, image_id, file_name)
        for declaration in declarations
    ]
    namespaced_traces = [_namespace_trace(trace, image_id) for trace in recovery.traces]

    return PackageImageAnalysis(
        image_id=image_id,
        file_name=file_name,
        ocr_engine=ocr.engine,
        ocr_text=ocr_text,
        image=ImageMetadata(width=ocr.width, height=ocr.height),
        regions=namespaced_regions,
        ocr_recovery=namespaced_traces,
        declarations=namespaced_declarations,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "packcheck-api", "version": "0.8.0", "ruleset": RULESET_ID}


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_package(
    files: Annotated[list[UploadFile] | None, File()] = None,
    override_text: Annotated[str | None, Form()] = None,
    imported_product: Annotated[bool, Form()] = False,
    may_become_unfit_for_human_consumption: Annotated[bool, Form()] = False,
    dimensions_relevant: Annotated[bool, Form()] = False,
    package_form: Annotated[PackageForm, Form()] = "single",
    alcoholic_beverage: Annotated[bool, Form()] = False,
    commodity_class: Annotated[CommodityClass, Form()] = "general",
) -> AnalysisResponse:
    uploads = list(files or [])
    manual_text = (override_text or "").strip()

    if not uploads and not manual_text:
        raise HTTPException(status_code=400, detail="Upload one or more package images or provide text to analyze.")
    if uploads and manual_text:
        raise HTTPException(status_code=400, detail="Use package images or manual text in one inspection, not both.")
    if len(uploads) > MAX_IMAGES:
        raise HTTPException(status_code=413, detail=f"A prototype inspection accepts at most {MAX_IMAGES} images.")

    context = PackageContext(
        imported_product=imported_product,
        may_become_unfit_for_human_consumption=may_become_unfit_for_human_consumption,
        dimensions_relevant=dimensions_relevant,
        package_form=package_form,
        alcoholic_beverage=alcoholic_beverage,
        commodity_class=commodity_class,
    )

    if manual_text:
        declarations, checks, summary = analyze_text_with_declarations(manual_text, context=context)
        return AnalysisResponse(
            input_mode="manual_text",
            file_names=["manual-text.txt"],
            image_count=0,
            images=[],
            ocr_text=manual_text,
            declarations=declarations,
            context=context,
            ruleset=RULESET_ID,
            rule_profile=PROFILE,
            summary=summary,
            checks=checks,
            disclaimer=DISCLAIMER,
        )

    payloads: list[tuple[UploadFile, bytes]] = []
    total_bytes = 0
    for upload in uploads:
        if upload.content_type and not upload.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail=f"'{upload.filename or 'upload'}' is not an image file.")
        raw = await upload.read()
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail=f"'{upload.filename or 'upload'}' is larger than the 10 MB per-image limit.")
        total_bytes += len(raw)
        if total_bytes > MAX_REQUEST_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Combined image size is larger than the 40 MB inspection limit.")
        payloads.append((upload, raw))

    engine = get_ocr_engine()
    image_results: list[PackageImageAnalysis] = []
    for index, (upload, raw) in enumerate(payloads, start=1):
        file_name = upload.filename or f"package-{index}.image"
        image_id = f"image-{index}"
        try:
            image_results.append(_analyze_image(raw, file_name, image_id, context, engine))
        except Exception as exc:  # pragma: no cover - environment specific
            raise HTTPException(status_code=422, detail=f"OCR failed for '{file_name}': {exc}") from exc

    combined_text = _combined_ocr_text(image_results)
    declarations = merge_image_declarations(image_results)
    checks, summary = evaluate_declarations(combined_text, declarations, context)

    return AnalysisResponse(
        input_mode="images",
        file_names=[image.file_name for image in image_results],
        image_count=len(image_results),
        images=image_results,
        ocr_text=combined_text,
        declarations=declarations,
        context=context,
        ruleset=RULESET_ID,
        rule_profile=PROFILE,
        summary=summary,
        checks=checks,
        disclaimer=DISCLAIMER,
    )
