import pytest
from reclamos_api.cases.brands import BRANDS, brand_of, brands_named


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bitel me cobra un plan", ["Bitel"]),
        ("TELEFÓNICA cortó mi línea", ["Movistar"]),
        ("pasé de Movistar a bitel", ["Movistar", "Bitel"]),
        ("tengo internet de Nextel", ["Entel"]),
        ("el twin del router no funciona", []),
        ("me cobran de más", []),
    ],
)
def test_brands_named_reads_brand_words_without_case_or_accents(
    text: str, expected: list[str]
) -> None:
    assert brands_named(text) == expected, text


def test_every_legal_name_belongs_to_one_brand() -> None:
    names = [name for names in BRANDS.values() for name in names]
    assert len(names) == len(set(names))
    assert brand_of("INTEGRATEL PERU S.A.A.") == "Movistar"
    assert brand_of("UNKNOWN S.A.") is None and brand_of(None) is None
