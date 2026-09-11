import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1] / "service"))
from app import app

client = TestClient(app)


def test_health_and_metrics():
    assert client.get("/health").json() == {"status": "ok"}
    assert "http_requests_total" in client.get("/metrics").text


def test_catalog_detail_cart_order_flow():
    catalog = client.get("/api/products?page=1&page_size=2")
    assert catalog.status_code == 200
    product_id = catalog.json()["items"][0]["id"]
    assert client.get(f"/api/products/{product_id}").status_code == 200
    cart = client.post("/api/cart", json={"product_id": product_id, "quantity": 1})
    assert cart.status_code == 200
    order = client.post("/api/orders", json={"cart_id": cart.json()["cart_id"]})
    assert order.status_code in (200, 502)
