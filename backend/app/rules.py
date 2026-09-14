from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

from .legal_profiles import PROFILE, PROFILE_ID, RULES, RuleDefinition
from .models import ComplianceSummary, DeclarationCheck, ExtractedDeclaration, PackageContext


RULESET_ID = PROFILE_ID


def _declaration_map(declarations: Iterable[ExtractedDeclaration]) -> dict[str, ExtractedDeclaration]:
    return {declaration.key: declaration for declaration in declarations}


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _normalized_quantity(declaration: ExtractedDeclaration | None) -> tuple[Decimal, str] | None:
    if declaration is None or declaration.attributes.get("multi_image_conflict") == "true":
        return None
    amount = _decimal(declaration.attributes.get("amount"))
    unit = declaration.attributes.get("unit")
    if amount is None or not unit:
        return None

    if unit == "mg":
        return amount / Decimal(1000), "g"
    if unit == "kg":
        return amount * Decimal(1000), "g"
    if unit == "cl":
        return amount * Decimal(10), "ml"
    if unit == "l":
        return amount * Decimal(1000), "ml"
    return amount, unit


def _is_small_package_exempt(
    facts: dict[str, ExtractedDeclaration],
    context: PackageContext,
) -> bool:
    # Rule 26(a): packages of 10 g / 10 ml or less are generally exempt.
    # The tobacco/tobacco-product proviso and the pan-masala proviso keep those
    # classes inside the rules, so only the general class is eligible here.
    if context.commodity_class != "general":
        return False

    quantity = _normalized_quantity(facts.get("net_quantity"))
    if not quantity:
        return False
    amount, unit = quantity
    return unit in {"g", "ml"} and amount <= Decimal(10)


def _prescribed_unit_basis(
    declaration: ExtractedDeclaration | None,
) -> tuple[Decimal, str] | None:
    quantity = _normalized_quantity(declaration)
    if not quantity:
        return None
    amount, unit = quantity

    if unit == "g":
        if amount < Decimal(1000):
            return amount, "g"
        return amount / Decimal(1000), "kg"
    if unit == "ml":
        if amount < Decimal(1000):
            return amount, "ml"
        return amount / Decimal(1000), "l"
    if unit == "pc":
        return amount, "pc"
    return None


def _unit_sale_price_equals_retail_price(
    facts: dict[str, ExtractedDeclaration],
) -> bool:
    basis = _prescribed_unit_basis(facts.get("net_quantity"))
    mrp = facts.get("mrp")
    if not basis or not mrp or mrp.attributes.get("multi_image_conflict") == "true":
        return False
    count_in_basis, _ = basis
    return count_in_basis == Decimal(1) and _decimal(mrp.attributes.get("amount")) is not None


def _not_applicable_message(rule: RuleDefinition, context: PackageContext) -> str:
    if rule.key == "country_origin":
        return "Not applicable because this scan was not marked as an imported product."
    if rule.key == "best_before":
        return "Not applicable because this scan was not marked as a commodity that may become unfit for human consumption."
    if rule.key == "dimensions":
        return "Not applicable because dimensions were not marked as relevant to this commodity."
    if rule.key == "unit_sale_price":
        if context.alcoholic_beverage:
            return "Not evaluated under this profile because alcoholic/spirituous beverage pricing is subject to the applicable State Excise regime."
        if context.package_form != "single":
            return "Not applicable under Rule 6(11) for the selected combination/group/multi-piece package form."
    return "This declaration is not applicable for the supplied package context."


def _validation_result(
    rule: RuleDefinition,
    declaration: ExtractedDeclaration,
    facts: dict[str, ExtractedDeclaration],
) -> tuple[str, str, float, float]:
    """Return status, message, confidence and earned-weight fraction."""
    if declaration.attributes.get("multi_image_conflict") == "true":
        candidates = declaration.attributes.get("candidate_values", declaration.value)
        return (
            "warning",
            f"Conflicting values were extracted from different package photos: {candidates}. Review the original images before determining compliance.",
            min(declaration.confidence, 0.70),
            0.45,
        )

    if rule.key == "manufacturer":
        if declaration.attributes.get("address_detected") != "true":
            return (
                "warning",
                "A responsible business identity was detected, but a complete address was not confidently associated with it. Review the package image.",
                min(declaration.confidence, 0.76),
                0.62,
            )
        return "pass", "Responsible business identity and address evidence detected.", declaration.confidence, 1.0

    if rule.key == "mrp":
        issues: list[str] = []
        if declaration.attributes.get("currency") != "INR":
            issues.append("no Indian-currency marker was captured")
        if declaration.attributes.get("tax_inclusive_phrase") != "true":
            issues.append("the 'inclusive of all taxes' wording was not captured")
        if issues:
            return (
                "warning",
                "MRP amount was detected, but " + " and ".join(issues) + ". Review the package image instead of assuming compliance.",
                min(declaration.confidence, 0.74),
                0.55,
            )
        return "pass", "MRP, Indian-currency marker and tax-inclusive wording detected.", declaration.confidence, 1.0

    if rule.key == "consumer_care":
        missing: list[str] = []
        if not declaration.attributes.get("phone"):
            missing.append("telephone number")
        if not declaration.attributes.get("email"):
            missing.append("e-mail address")
        if declaration.attributes.get("address_detected") != "true":
            missing.append("consumer-care address")
        if missing:
            return (
                "warning",
                "Consumer-care evidence was detected, but the following could not be fully verified: " + ", ".join(missing) + ".",
                min(declaration.confidence, 0.76),
                0.62,
            )
        return "pass", "Consumer-care address, telephone number and e-mail evidence detected.", declaration.confidence, 1.0

    if rule.key == "unit_sale_price":
        net_quantity = facts.get("net_quantity")
        mrp = facts.get("mrp")
        if (net_quantity and net_quantity.attributes.get("multi_image_conflict") == "true") or (
            mrp and mrp.attributes.get("multi_image_conflict") == "true"
        ):
            return (
                "warning",
                "Unit sale price arithmetic was not evaluated because MRP or net quantity conflicts across package photos must be resolved first.",
                min(declaration.confidence, 0.68),
                0.45,
            )
        basis = _prescribed_unit_basis(net_quantity)
        usp_amount = _decimal(declaration.attributes.get("amount"))
        reference_quantity = _decimal(declaration.attributes.get("reference_quantity"))
        reference_unit = declaration.attributes.get("reference_unit")

        if not basis or not mrp or usp_amount is None or reference_quantity is None:
            return (
                "warning",
                "Unit sale price was detected, but the prototype could not validate its prescribed basis/calculation from the available MRP and net quantity.",
                min(declaration.confidence, 0.72),
                0.55,
            )

        quantity_in_basis, expected_unit = basis
        if reference_quantity != Decimal(1) or reference_unit != expected_unit:
            return (
                "fail",
                f"Unit sale price uses '{reference_quantity} {reference_unit}' as the denominator; Rule 6(11) requires a per-{expected_unit} basis for this net quantity.",
                declaration.confidence,
                0.0,
            )

        mrp_amount = _decimal(mrp.attributes.get("amount"))
        if mrp_amount is None or quantity_in_basis <= 0:
            return (
                "warning",
                "Unit sale price basis is structurally valid, but its arithmetic could not be checked against the MRP.",
                min(declaration.confidence, 0.75),
                0.7,
            )

        expected = (mrp_amount / quantity_in_basis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual = usp_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if actual != expected:
            return (
                "fail",
                f"Unit sale price arithmetic does not match the extracted MRP/net quantity. Expected INR {expected:.2f} per {expected_unit}, found INR {actual:.2f}.",
                declaration.confidence,
                0.0,
            )
        return (
            "pass",
            f"Unit sale price uses the prescribed per-{expected_unit} basis and matches the extracted MRP/net quantity after two-decimal rounding.",
            declaration.confidence,
            1.0,
        )

    messages = {
        "country_origin": "Country-of-origin/manufacture/assembly declaration detected for the imported product context.",
        "commodity_name": "Common/generic commodity-name declaration detected.",
        "net_quantity": "Net quantity detected with a recognized unit.",
        "month_year": "Manufacture/packing/import month and year detected.",
        "best_before": "Best-before/use-by declaration detected for the selected package context.",
        "dimensions": "Size/dimension declaration detected for the selected package context.",
    }
    return "pass", messages.get(rule.key, "Required declaration detected."), declaration.confidence, 1.0


def evaluate_declarations(
    raw_text: str,
    declarations: Iterable[ExtractedDeclaration],
    context: PackageContext | None = None,
) -> tuple[list[DeclarationCheck], ComplianceSummary]:
    context = context or PackageContext()
    facts = _declaration_map(declarations)
    checks: list[DeclarationCheck] = []

    small_package_exempt = _is_small_package_exempt(facts, context)
    weighted_points = Decimal(0)
    total_weight = 0

    for rule in RULES:
        declaration = facts.get(rule.key)

        if small_package_exempt:
            checks.append(
                DeclarationCheck(
                    rule_id=rule.rule_id,
                    key=rule.key,
                    label=rule.label,
                    legal_reference=rule.legal_reference,
                    requirement=rule.requirement,
                    applicability="not_applicable",
                    status="not_applicable",
                    value=declaration.value if declaration else None,
                    evidence=declaration.evidence if declaration else None,
                    confidence=1.0,
                    message=(
                        "Not applicable under this profile because the extracted package quantity is 10 g/10 ml or less "
                        "and the commodity class is not tobacco or pan masala (Rule 26(a) small-package exemption)."
                    ),
                    region_ids=declaration.region_ids if declaration else [],
                    source_image_ids=declaration.source_image_ids if declaration else [],
                    attributes=declaration.attributes if declaration else {},
                )
            )
            continue

        applicable = rule.applies(context)
        if rule.key == "unit_sale_price" and applicable and _unit_sale_price_equals_retail_price(facts):
            applicable = False
            not_applicable_message = (
                "Not applicable because the extracted retail sale price equals the computed unit sale price for the prescribed unit basis."
            )
        else:
            not_applicable_message = _not_applicable_message(rule, context)

        if not applicable:
            checks.append(
                DeclarationCheck(
                    rule_id=rule.rule_id,
                    key=rule.key,
                    label=rule.label,
                    legal_reference=rule.legal_reference,
                    requirement=rule.requirement,
                    applicability="not_applicable",
                    status="not_applicable",
                    value=declaration.value if declaration else None,
                    evidence=declaration.evidence if declaration else None,
                    confidence=1.0,
                    message=not_applicable_message,
                    region_ids=declaration.region_ids if declaration else [],
                    source_image_ids=declaration.source_image_ids if declaration else [],
                    attributes=declaration.attributes if declaration else {},
                )
            )
            continue

        total_weight += rule.weight

        if declaration:
            status, message, confidence, fraction = _validation_result(rule, declaration, facts)
            weighted_points += Decimal(str(rule.weight)) * Decimal(str(fraction))
            checks.append(
                DeclarationCheck(
                    rule_id=rule.rule_id,
                    key=rule.key,
                    label=rule.label,
                    legal_reference=rule.legal_reference,
                    requirement=rule.requirement,
                    applicability="required",
                    status=status,  # type: ignore[arg-type]
                    value=declaration.value,
                    evidence=declaration.evidence,
                    confidence=confidence,
                    message=message,
                    region_ids=declaration.region_ids,
                    source_image_ids=declaration.source_image_ids,
                    attributes=declaration.attributes,
                )
            )
            continue

        if rule.key == "mrp" and facts.get("mrp_reference"):
            reference = facts["mrp_reference"]
            weighted_points += Decimal(str(rule.weight)) * Decimal("0.25")
            checks.append(
                DeclarationCheck(
                    rule_id=rule.rule_id,
                    key=rule.key,
                    label=rule.label,
                    legal_reference=rule.legal_reference,
                    requirement=rule.requirement,
                    applicability="required",
                    status="warning",
                    value=None,
                    evidence=reference.evidence,
                    confidence=min(reference.confidence, 0.72),
                    message=(
                        "An MRP locator reference was detected, but the computer-vision / multi-view OCR recovery path could not establish the actual price. "
                        "Treat this as unresolved evidence, not as proof that the package omits MRP."
                    ),
                    region_ids=reference.region_ids,
                    source_image_ids=reference.source_image_ids,
                    attributes=reference.attributes,
                )
            )
            continue

        checks.append(
            DeclarationCheck(
                rule_id=rule.rule_id,
                key=rule.key,
                label=rule.label,
                legal_reference=rule.legal_reference,
                requirement=rule.requirement,
                applicability="required",
                status="fail",
                value=None,
                evidence=None,
                confidence=0.88 if raw_text.strip() else 0.0,
                message="Required declaration could not be detected for the supplied package context.",
                region_ids=[],
                attributes={},
            )
        )

    compact = re.sub(r"\W+", "", raw_text)
    if len(compact) < 40:
        for check in checks:
            if check.status == "fail":
                check.status = "warning"
                check.message = (
                    "OCR text is too limited to reliably verify this required declaration. Retake a clearer image before treating it as missing."
                )
                check.confidence = min(check.confidence, 0.35)

    passed = sum(check.status == "pass" for check in checks)
    warnings = sum(check.status == "warning" for check in checks)
    failed = sum(check.status == "fail" for check in checks)
    not_applicable = sum(check.status == "not_applicable" for check in checks)

    if total_weight == 0:
        score: int | None = None
        overall = "not_applicable"
    else:
        score = round(float(weighted_points) * 100 / total_weight)
        overall = "fail" if failed else ("warning" if warnings else "pass")

    return checks, ComplianceSummary(
        score=score,
        status=overall,  # type: ignore[arg-type]
        passed=passed,
        warnings=warnings,
        failed=failed,
        not_applicable=not_applicable,
    )
