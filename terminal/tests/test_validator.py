import pytest

from validator import clean_input, normalize


@pytest.mark.parametrize("raw", ["(650) 253-0000", "650-253-0000", "6502530000", "16502530000",
                                 "+1 650 253 0000", "+16502530000", "16502530000.0", "  650.253.0000 "])
def test_us_formats_normalize_to_e164(raw):
    result = normalize(raw, "US")
    assert result.valid
    assert result.e164 == "+16502530000"
    assert result.country == "US"


@pytest.mark.parametrize("raw", ["", None, "abc", "123", "+1 000 000 0000", "nan", "650-ABC-0000"])
def test_invalid_numbers_rejected(raw):
    result = normalize(raw, "US")
    assert not result.valid
    assert result.e164 is None
    assert result.error


def test_international_number_with_plus():
    result = normalize("+44 20 7946 0958", "US")
    assert result.valid and result.e164 == "+442079460958" and result.country == "GB"


def test_double_zero_prefix():
    assert normalize("0016502530000", "US").e164 == "+16502530000"


def test_clean_input_strips_float_artifacts_and_quotes():
    assert clean_input("'6502530000'") == "6502530000"
    assert clean_input(16502530000.0) == "16502530000"
