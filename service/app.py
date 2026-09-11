import asyncio
import random
import time
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="Game Mall Performance Lab", version="1.0.0")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
DEPENDENCY_LATENCY = Histogram(
    "dependency_duration_seconds",
    "Simulated downstream dependency latency",
    ["dependency"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
DEPENDENCY_ERRORS = Counter(
    "dependency_errors_total", "Simulated downstream errors", ["dependency"]
)

PRODUCTS = [
    {"id": i, "name": f"Epic Sword {i}", "price": round(99 + i * 3.5, 2), "stock": 1000}
    for i in range(1, 101)
]


async def dependency_call(name: str, base_ms: float, jitter_ms: float, error_rate: float = 0.0) -> None:
    started = time.perf_counter()
    delay = max(0.0, random.gauss(base_ms, jitter_ms)) / 1000
    await asyncio.sleep(delay)
    DEPENDENCY_LATENCY.labels(name).observe(time.perf_counter() - started)
    if random.random() < error_rate:
        DEPENDENCY_ERRORS.labels(name).inc()
        raise RuntimeError(f"{name} unavailable")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = None
    status = "500"
    route = request.url.path
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, route, status).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/products")
async def list_products(
    q: str = Query(default="", max_length=80),
    page: Annotated[int, Query(ge=1, le=100)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    # q=slow makes the database evidence obvious during the lab.
    db_ms = 130 if q.lower() == "slow" else 25
    try:
        await dependency_call("postgres", db_ms, 25)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="catalog database unavailable")
    filtered = [p for p in PRODUCTS if q.lower() in p["name"].lower()]
    begin = (page - 1) * page_size
    return {"items": filtered[begin : begin + page_size], "total": len(filtered), "page": page}


@app.get("/api/products/{product_id}")
async def product_detail(product_id: int):
    # A 75% cache hit ratio keeps this endpoint faster than search.
    if random.random() < 0.75:
        await dependency_call("redis", 4, 2)
    else:
        await dependency_call("redis", 4, 2)
        await dependency_call("postgres", 80, 20)
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise HTTPException(status_code=404, detail="product not found")


@app.post("/api/cart")
async def add_to_cart(payload: dict):
    product_id = int(payload.get("product_id", 1))
    quantity = int(payload.get("quantity", 1))
    if quantity < 1 or quantity > 10:
        raise HTTPException(status_code=400, detail="quantity must be between 1 and 10")
    if not any(p["id"] == product_id for p in PRODUCTS):
        raise HTTPException(status_code=404, detail="product not found")
    try:
        await dependency_call("redis", 8, 3)
        await dependency_call("postgres", 35, 10)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="cart dependency unavailable")
    return {"cart_id": f"cart-{product_id}", "product_id": product_id, "quantity": quantity}


@app.post("/api/orders")
async def create_order(payload: dict):
    if not payload.get("cart_id"):
        raise HTTPException(status_code=400, detail="cart_id is required")
    try:
        await dependency_call("postgres", 70, 20)
        await dependency_call("payment", 120, 45, error_rate=0.015)
    except RuntimeError:
        raise HTTPException(status_code=502, detail="payment provider unavailable")
    return {"order_id": f"order-{random.randint(100000, 999999)}", "status": "paid"}
