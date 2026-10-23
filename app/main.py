"""Payment API: product catalog, payments, a slow /checkout and an unreliable /flaky endpoint."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.routing import Match

from app import catalog
from app.config import Settings
from app.telemetry import Telemetry, configure_logging

logger = logging.getLogger("payment-api")
tracer = trace.get_tracer("payment-api")

# Endpoints that are not part of the user-facing SLI.
UNTRACKED_PATHS = {"/metrics", "/healthz", "/readyz"}


class PaymentRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    card_number: str = Field(min_length=12, max_length=23)


class FlakyError(Exception):
    """Simulated downstream failure raised by /flaky."""


def route_template(app: FastAPI, scope) -> str:
    """Return the route path template (e.g. /api/v1/products/{product_id}) to keep label cardinality low."""
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route.path
    return "unmatched"


def create_app(settings: Settings | None = None, rng: random.Random | None = None) -> FastAPI:
    settings = settings or Settings()
    rng = rng or random.Random()
    configure_logging(settings)
    telemetry = Telemetry(settings)

    app = FastAPI(title="Payment API", version=settings.version)
    app.state.settings = settings
    app.state.rng = rng

    in_flight = {"count": 0}

    @app.middleware("http")
    async def red_metrics(request: Request, call_next):
        if request.url.path in UNTRACKED_PATHS:
            return await call_next(request)
        start = time.perf_counter()
        path = route_template(app, request.scope)
        status = 500
        in_flight["count"] += 1
        telemetry.in_flight.add(1)
        try:
            if settings.max_in_flight and in_flight["count"] > settings.max_in_flight:
                status = 503
                return JSONResponse(
                    status_code=503,
                    content={"detail": "overloaded, retry later"},
                    headers={"Retry-After": "1"},
                )
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            in_flight["count"] -= 1
            telemetry.in_flight.add(-1)
            elapsed = time.perf_counter() - start
            labels = {"method": request.method, "route": path, "status_code": str(status)}
            telemetry.requests.add(1, labels)
            telemetry.duration.record(elapsed, labels)
            logger.log(
                logging.WARNING if status >= 500 else logging.INFO,
                "request handled",
                extra={
                    "http_method": request.method,
                    "http_route": path,
                    "http_status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )

    @app.exception_handler(FlakyError)
    async def flaky_handler(_: Request, exc: FlakyError):
        logger.error("downstream failure", extra={"error": str(exc)})
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        return {"status": "ready", "version": settings.version}

    @app.get("/metrics")
    async def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/v1/products")
    async def products():
        return [vars(p) for p in catalog.list_products()]

    @app.get("/api/v1/products/{product_id}")
    async def product(product_id: int):
        item = catalog.get_product(product_id)
        if item is None:
            raise HTTPException(status_code=404, detail="product not found")
        return vars(item)

    @app.post("/api/v1/payments", status_code=201)
    async def create_payment(payment: PaymentRequest):
        item = catalog.get_product(payment.product_id)
        if item is None:
            telemetry.payments.add(1, {"outcome": "unknown_product"})
            raise HTTPException(status_code=404, detail="product not found")
        if not catalog.luhn_valid(payment.card_number):
            telemetry.payments.add(1, {"outcome": "invalid_card"})
            raise HTTPException(status_code=422, detail="invalid card number")
        try:
            total = catalog.compute_total(item, payment.quantity, payment.currency.upper())
        except catalog.PaymentError as exc:
            telemetry.payments.add(1, {"outcome": "rejected"})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payment_id = str(uuid.uuid4())
        telemetry.payments.add(1, {"outcome": "accepted"})
        logger.info("payment accepted", extra={"payment_id": payment_id, "amount_cents": total})
        return {
            "payment_id": payment_id,
            "product_id": item.id,
            "quantity": payment.quantity,
            "currency": payment.currency.upper(),
            "amount_cents": total,
            "card": catalog.mask_card(payment.card_number),
            "status": "accepted",
        }

    @app.get("/checkout")
    async def checkout():
        """Simulated slow processing: nominal latency plus a few very slow requests."""
        with tracer.start_as_current_span("checkout.process") as span:
            if rng.random() < settings.checkout_slow_ratio:
                delay_ms = settings.checkout_slow_ms
                span.set_attribute("checkout.slow_path", True)
            else:
                delay_ms = rng.uniform(settings.checkout_min_ms, settings.checkout_max_ms)
            span.set_attribute("checkout.delay_ms", delay_ms)
            await asyncio.sleep(delay_ms / 1000)
            if rng.random() < settings.checkout_error_rate:
                raise FlakyError("payment gateway unavailable")
        return {"status": "processed", "delay_ms": round(delay_ms, 2)}

    @app.get("/flaky")
    async def flaky(error_rate: float | None = Query(default=None, ge=0.0, le=1.0)):
        """Fails intermittently with HTTP 500 (rate overridable per request)."""
        rate = settings.flaky_error_rate if error_rate is None else error_rate
        if rng.random() < rate:
            raise FlakyError("simulated downstream failure")
        return {"status": "ok"}

    telemetry.instrument(app)
    return app


app = create_app()
