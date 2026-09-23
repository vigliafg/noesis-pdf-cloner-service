"""Test del parsing della specifica pagine."""

import pytest

from app.pages import PageSpecError, describe_pages, format_pages_label, parse_pages


def test_all_pages():
    assert parse_pages("all", 5) == [0, 1, 2, 3, 4]
    assert parse_pages("", 3) == [0, 1, 2]
    assert parse_pages(None, 3) == [0, 1, 2]


def test_single_page():
    assert parse_pages("7", 10) == [6]


def test_range():
    assert parse_pages("100-103", 200) == [99, 100, 101, 102]


def test_range_reversed_is_normalised():
    assert parse_pages("103-100", 200) == [99, 100, 101, 102]


def test_list_with_spaces_and_duplicates():
    assert parse_pages(" 3, 5 , 10-12, 3 ", 20) == [2, 4, 9, 10, 11]


def test_out_of_range_raises():
    with pytest.raises(ValueError):
        parse_pages("11", 10)
    with pytest.raises(ValueError):
        parse_pages("0", 10)
    with pytest.raises(ValueError):
        parse_pages("1-11", 10)


def test_invalid_token_raises():
    with pytest.raises(ValueError):
        parse_pages("abc", 10)
    with pytest.raises(ValueError):
        parse_pages("1-", 10)


def test_label_and_describe():
    assert format_pages_label([0]) == "1"
    assert format_pages_label([99, 100, 101, 102]) == "100-103"
    assert format_pages_label([2, 4, 9]) == "3,5,10"
    assert format_pages_label([0, 2, 6, 7, 8]) == "1,3,7-9"
    assert describe_pages([155]) == "pagina 156"
    assert "4 pagine" in describe_pages([99, 100, 101, 102])


def test_error_codes_are_stable():
    """I ``code`` sono usati dalla UI desktop per tradurre il messaggio."""
    assert issubclass(PageSpecError, ValueError)
    with pytest.raises(PageSpecError) as exc:
        parse_pages("11", 10)
    assert exc.value.code == "bounds"
    with pytest.raises(PageSpecError) as exc:
        parse_pages("abc", 10)
    assert exc.value.code == "token"
    with pytest.raises(PageSpecError) as exc:
        parse_pages("1-", 10)
    assert exc.value.code == "range"
    with pytest.raises(PageSpecError) as exc:
        parse_pages("1,,2", 10)
    assert exc.value.code == "empty"
    with pytest.raises(PageSpecError) as exc:
        parse_pages("1", 0)
    assert exc.value.code == "no_pages"
