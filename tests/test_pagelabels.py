"""Test dell'espansione delle etichette di pagina (/PageLabels)."""

from app.pagelabels import build_page_labels, format_number


def test_format_number_styles():
    assert format_number(3, "D") == "3"
    assert format_number(4, "R") == "IV"
    assert format_number(4, "r") == "iv"
    assert format_number(1, "A") == "A"
    assert format_number(27, "a") == "aa"
    assert format_number(5, "") == ""


def test_fallback_to_physical_numbers():
    assert build_page_labels([], 3) == ["1", "2", "3"]
    assert build_page_labels(None, 2) == ["1", "2"]


def test_roman_then_decimal():
    spec = [
        {"startpage": 0, "style": "r", "firstpagenum": 1},
        {"startpage": 3, "style": "D", "firstpagenum": 1},
    ]
    assert build_page_labels(spec, 5) == ["i", "ii", "iii", "1", "2"]


def test_prefix_and_no_style():
    spec = [
        {"startpage": 0, "style": "", "prefix": "Cop"},
        {"startpage": 1, "style": "D", "prefix": "A-", "firstpagenum": 1},
    ]
    assert build_page_labels(spec, 3) == ["Cop", "A-1", "A-2"]


def test_uncovered_pages_use_physical():
    spec = [{"startpage": 2, "style": "D", "firstpagenum": 10}]
    assert build_page_labels(spec, 4) == ["1", "2", "10", "11"]
