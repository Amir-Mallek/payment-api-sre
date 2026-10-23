import pytest

from app import catalog
from app.catalog import PaymentError, Product

VALID_CARD = "4539 1488 0343 6467"


def test_list_products_returns_all_items():
    assert len(catalog.list_products()) == len(catalog.PRODUCTS)


def test_get_product_known_and_unknown():
    assert catalog.get_product(1).name == "Mechanical keyboard"
    assert catalog.get_product(999) is None


@pytest.mark.parametrize("number", [VALID_CARD, "4111111111111111", "5555555555554444", "378282246310005"])
def test_luhn_accepts_valid_numbers(number):
    assert catalog.luhn_valid(number)


@pytest.mark.parametrize(
    "number",
    [
        "4111111111111112",  # bad checksum
        "4111-1111-1111-1111",  # non digit characters
        "12345678901",  # too short (11 digits)
        "1" * 20,  # too long
        "",
    ],
)
def test_luhn_rejects_invalid_numbers(number):
    assert not catalog.luhn_valid(number)


def test_mask_card_keeps_last_four_digits():
    assert catalog.mask_card(VALID_CARD) == "************6467"


def test_compute_total_converts_currency():
    product = Product(99, "test", 1000, 10)
    assert catalog.compute_total(product, 2, "EUR") == 2000
    assert catalog.compute_total(product, 1, "USD") == 1080
    assert catalog.compute_total(product, 3, "TND") == 10050


@pytest.mark.parametrize(
    ("quantity", "currency", "message"),
    [
        (1, "GBP", "unsupported currency"),
        (0, "EUR", "quantity must be between"),
        (101, "EUR", "quantity must be between"),
        (11, "EUR", "insufficient stock"),
    ],
)
def test_compute_total_edge_cases(quantity, currency, message):
    product = Product(99, "test", 1000, 10)
    with pytest.raises(PaymentError, match=message):
        catalog.compute_total(product, quantity, currency)


def test_compute_total_allows_exact_stock_and_max_quantity():
    product = Product(99, "test", 100, catalog.MAX_QUANTITY)
    assert catalog.compute_total(product, catalog.MAX_QUANTITY, "EUR") == 100 * catalog.MAX_QUANTITY
