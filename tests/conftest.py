import random

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FixedRandom(random.Random):
    """Random generator whose random() returns a scripted value."""

    def __init__(self, value: float) -> None:
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


def make_client(rng_value: float = 0.5, **overrides) -> TestClient:
    settings = Settings(checkout_min_ms=0, checkout_max_ms=1, checkout_slow_ms=5, **overrides)
    return TestClient(create_app(settings, FixedRandom(rng_value)))


@pytest.fixture
def client() -> TestClient:
    return make_client()
