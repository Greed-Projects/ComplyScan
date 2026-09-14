from app.extraction import extract_declarations


def test_extraction_builds_normalized_declaration_facts():
    text = """
    Product Name: Roasted Peanuts
    Manufactured by: Innovate Foods Pvt Ltd, Sector 62, Noida, Uttar Pradesh 201309
    Country of Origin: India
    Net Quantity: 200 g
    MRP: INR 99.00 Inclusive of all taxes
    Mfg Date: 08/2026
    Best Before: 6 months from packing
    Dimensions: 10 cm x 20 cm x 5 cm
    Consumer Care: Innovate Foods Pvt Ltd, Sector 62, Noida 201309 | care@innovatefoods.example | 9876543210
    Unit Sale Price: Rs 0.50 / g
    """

    declarations = {item.key: item for item in extract_declarations(text)}

    assert declarations["manufacturer"].value.startswith("Innovate Foods Pvt Ltd")
    assert declarations["manufacturer"].attributes["address_detected"] == "true"
    assert declarations["country_origin"].attributes == {"country": "India"}
    assert declarations["net_quantity"].attributes == {"amount": "200", "unit": "g"}
    assert declarations["mrp"].attributes == {
        "amount": "99.00",
        "tax_inclusive_phrase": "true",
        "currency": "INR",
    }
    assert declarations["month_year"].attributes == {"month": "08", "year": "2026"}
    assert declarations["best_before"].value == "6 months from packing"
    assert declarations["dimensions"].value == "10 cm x 20 cm x 5 cm"
    assert declarations["consumer_care"].attributes["phone"] == "9876543210"
    assert declarations["consumer_care"].attributes["address_detected"] == "true"
    assert declarations["unit_sale_price"].attributes == {
        "currency": "INR",
        "amount": "0.50",
        "reference_quantity": "1",
        "reference_unit": "g",
    }


def test_unit_sale_price_denominator_is_not_mistaken_for_net_quantity():
    text = "Unit Sale Price: Rs 49.50 / 100 g"
    declarations = {item.key: item for item in extract_declarations(text)}
    assert "unit_sale_price" in declarations
    assert "net_quantity" not in declarations
