"""Business logic of the payment API: product catalog, card validation, pricing."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_CURRENCIES = {"EUR": 1.0, "USD": 1.08, "TND": 3.35}
MAX_QUANTITY = 100


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    price_cents: int  # price in EUR cents
    stock: int


PRODUCTS: dict[int, Product] = {
    1: Product(1, "Mechanical keyboard", 8999, 42),
    2: Product(2, "Wireless mouse", 2999, 120),
    3: Product(3, "27-inch monitor", 24999, 7),
    4: Product(4, "USB-C hub", 3499, 0),
}


class PaymentError(ValueError):
    """Raised when a payment request is semantically invalid."""


def list_products() -> list[Product]:
    return list(PRODUCTS.values())


def get_product(product_id: int) -> Product | None:
    return PRODUCTS.get(product_id)


def luhn_valid(card_number: str) -> bool:
    """Validate a card number with the Luhn checksum."""
    digits = card_number.replace(" ", "")
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def mask_card(card_number: str) -> str:
    digits = card_number.replace(" ", "")
    return "*" * (len(digits) - 4) + digits[-4:]


def compute_total(product: Product, quantity: int, currency: str) -> int:
    """Return the total price in cents of `currency`."""
    if currency not in SUPPORTED_CURRENCIES:
        raise PaymentError(f"unsupported currency: {currency}")
    if not 1 <= quantity <= MAX_QUANTITY:
        raise PaymentError(f"quantity must be between 1 and {MAX_QUANTITY}")
    if quantity > product.stock:
        raise PaymentError("insufficient stock")
    return round(product.price_cents * quantity * SUPPORTED_CURRENCIES[currency])
