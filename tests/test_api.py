from tests.conftest import make_client

VALID_CARD = "4111111111111111"


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    body = client.get("/readyz").json()
    assert body["status"] == "ready"
    assert "version" in body


def test_list_products(client):
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    assert {p["id"] for p in response.json()} == {1, 2, 3, 4}


def test_get_product(client):
    assert client.get("/api/v1/products/2").json()["name"] == "Wireless mouse"


def test_get_unknown_product_returns_404(client):
    assert client.get("/api/v1/products/404").status_code == 404


def test_get_product_with_invalid_id_returns_422(client):
    assert client.get("/api/v1/products/abc").status_code == 422


def test_payment_accepted(client):
    response = client.post(
        "/api/v1/payments",
        json={"product_id": 1, "quantity": 2, "currency": "usd", "card_number": VALID_CARD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "accepted"
    assert body["currency"] == "USD"
    assert body["amount_cents"] == round(8999 * 2 * 1.08)
    assert body["card"].endswith("1111")
    assert VALID_CARD not in response.text


def test_payment_unknown_product(client):
    response = client.post("/api/v1/payments", json={"product_id": 77, "card_number": VALID_CARD})
    assert response.status_code == 404


def test_payment_invalid_card(client):
    response = client.post("/api/v1/payments", json={"product_id": 1, "card_number": "4111111111111112"})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid card number"


def test_payment_out_of_stock(client):
    response = client.post("/api/v1/payments", json={"product_id": 4, "card_number": VALID_CARD})
    assert response.status_code == 422
    assert response.json()["detail"] == "insufficient stock"


def test_payment_schema_validation(client):
    assert client.post("/api/v1/payments", json={"product_id": 1}).status_code == 422
    assert client.post("/api/v1/payments", json={"product_id": 1, "card_number": "123"}).status_code == 422


def test_checkout_nominal_path():
    client = make_client(rng_value=0.9, checkout_slow_ratio=0.1)
    body = client.get("/checkout").json()
    assert body["status"] == "processed"
    assert 0 <= body["delay_ms"] <= 1


def test_checkout_slow_path():
    client = make_client(rng_value=0.01, checkout_slow_ratio=0.1)
    assert client.get("/checkout").json()["delay_ms"] == 5


def test_flaky_success():
    assert make_client(rng_value=0.9, flaky_error_rate=0.5).get("/flaky").status_code == 200


def test_flaky_failure():
    response = make_client(rng_value=0.1, flaky_error_rate=0.5).get("/flaky")
    assert response.status_code == 500
    assert response.json()["detail"] == "simulated downstream failure"


def test_flaky_rate_override(client):
    assert client.get("/flaky", params={"error_rate": 1}).status_code == 500
    assert client.get("/flaky", params={"error_rate": 0}).status_code == 200
    assert client.get("/flaky", params={"error_rate": 2}).status_code == 422


def test_metrics_exposes_red_metrics(client):
    client.get("/flaky", params={"error_rate": 1})
    client.get("/api/v1/products")
    text = client.get("/metrics").text
    assert 'http_server_requests_total{method="GET",route="/flaky",status_code="500"}' in text
    assert 'http_server_request_duration_seconds_bucket{le="0.2"' in text
    assert "payments_processed_total" in text or "http_server_requests_total" in text


def test_untracked_paths_are_excluded_from_sli(client):
    client.get("/healthz")
    assert 'route="/healthz"' not in client.get("/metrics").text


def test_unmatched_route_is_recorded(client):
    assert client.get("/does-not-exist").status_code == 404
    assert 'route="unmatched"' in client.get("/metrics").text


def test_load_shedding_returns_503_when_overloaded():
    client = make_client(max_in_flight=-1)  # any in-flight request exceeds the limit
    response = client.get("/api/v1/products")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert 'route="/api/v1/products",status_code="503"' in client.get("/metrics").text


def test_health_endpoints_bypass_load_shedding():
    assert make_client(max_in_flight=-1).get("/healthz").status_code == 200


def test_checkout_fails_when_payment_gateway_is_down():
    response = make_client(rng_value=0.5, checkout_error_rate=1.0).get("/checkout")
    assert response.status_code == 500
    assert response.json()["detail"] == "payment gateway unavailable"
