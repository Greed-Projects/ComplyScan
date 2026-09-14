from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import PackageContext, RuleProfileMetadata


PROFILE_ID = "india-lmpc-retail-package-2026-05-29-v1"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    key: str
    label: str
    legal_reference: str
    requirement: str
    weight: int
    applies: Callable[[PackageContext], bool]


def _always(_: PackageContext) -> bool:
    return True


def _imported(context: PackageContext) -> bool:
    return context.imported_product


def _perishable(context: PackageContext) -> bool:
    return context.may_become_unfit_for_human_consumption


def _dimensions(context: PackageContext) -> bool:
    return context.dimensions_relevant


def _unit_sale_price(context: PackageContext) -> bool:
    if context.alcoholic_beverage:
        return False
    return context.package_form == "single"


RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        rule_id="LMPC-6-1-a",
        key="manufacturer",
        label="Manufacturer / Packer / Importer",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(a)",
        requirement="Name and address of the responsible manufacturer/packer/importer must be declared, subject to product-specific provisos.",
        weight=14,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-aa",
        key="country_origin",
        label="Country of Origin / Manufacture / Assembly",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(aa)",
        requirement="Imported products must declare the country of origin, manufacture or assembly.",
        weight=8,
        applies=_imported,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-b",
        key="commodity_name",
        label="Common / Generic Name",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(b)",
        requirement="The common or generic name of the commodity must be declared.",
        weight=10,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-c",
        key="net_quantity",
        label="Net Quantity",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(c)",
        requirement="Net quantity must be declared in the applicable standard unit of weight, measure or number.",
        weight=16,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-d",
        key="month_year",
        label="Month & Year of Manufacture / Packing / Import",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(d)",
        requirement="The applicable month and year of manufacture, pre-packing or import must be declared, subject to statutory category-specific provisos.",
        weight=10,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-da",
        key="best_before",
        label="Best Before / Use By",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(da)",
        requirement="Where the commodity may become unfit for human consumption, the applicable best-before/use-by declaration must be present.",
        weight=6,
        applies=_perishable,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-e",
        key="mrp",
        label="Maximum Retail Price (MRP)",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(e)",
        requirement="Retail sale price must be declared as MRP in Indian currency and inclusive of all taxes, subject to statutory exemptions.",
        weight=16,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-1-f",
        key="dimensions",
        label="Size / Dimensions",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(1)(f)",
        requirement="Where dimensions are relevant to the commodity, the applicable dimensions must be declared.",
        weight=4,
        applies=_dimensions,
    ),
    RuleDefinition(
        rule_id="LMPC-6-2",
        key="consumer_care",
        label="Consumer Care Details",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(2)",
        requirement="Consumer complaint contact details must include the required name/address, telephone number and e-mail address.",
        weight=12,
        applies=_always,
    ),
    RuleDefinition(
        rule_id="LMPC-6-11",
        key="unit_sale_price",
        label="Unit Sale Price",
        legal_reference="Legal Metrology (Packaged Commodities) Rules, 2011 — Rule 6(11)",
        requirement="Unit sale price must be declared in rupees to the prescribed measurement basis and rounded to two decimal places, unless an exemption applies.",
        weight=4,
        applies=_unit_sale_price,
    ),
)


PROFILE = RuleProfileMetadata(
    id=PROFILE_ID,
    title="India LMPC physical retail-package declaration profile",
    jurisdiction="India",
    legal_basis=(
        "Legal Metrology (Packaged Commodities) Rules, 2011, with relevant declaration amendments "
        "and the amendment history checked through G.S.R. 418(E), 29 May 2026."
    ),
    checked_through="2026-09-13",
    scope=(
        "Prototype screening of declarations visible on a physical retail package. Applicability is resolved from "
        "explicit package context plus extracted facts; absent context is not silently guessed."
    ),
    exclusions=[
        "Font-size and numeral/letter geometry under Rules 7-9 are not yet measured.",
        "Principal display panel geometry is not yet validated.",
        "E-commerce listing-only obligations, including Rule 6(10A), are outside this physical-package profile.",
        "Specialized regimes and product-specific provisos (for example food, drugs/cosmetics and medical devices) require dedicated profiles.",
    ],
)
