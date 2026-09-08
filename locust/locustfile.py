import os
import random
import uuid

from locust import HttpUser, between, task


class MallUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.user_id = str(uuid.uuid4())
        self.product_id = random.randint(1, 100)

    @task(35)
    def browse_products(self):
        with self.client.get(
            "/api/products?page=1&page_size=20",
            name="GET /api/products",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"catalog status={response.status_code}")

    @task(20)
    def search_products(self):
        query = random.choice(["Sword", "Epic", "", "slow"])
        with self.client.get(
            "/api/products",
            params={"q": query, "page": 1, "page_size": 20},
            name="GET /api/products?q",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"search status={response.status_code}")

    @task(25)
    def view_detail(self):
        with self.client.get(
            f"/api/products/{self.product_id}",
            name="GET /api/products/{id}",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 404):
                response.failure(f"detail status={response.status_code}")

    @task(12)
    def add_cart(self):
        with self.client.post(
            "/api/cart",
            json={"product_id": self.product_id, "quantity": random.randint(1, 2)},
            name="POST /api/cart",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"cart status={response.status_code}")

    @task(8)
    def checkout(self):
        with self.client.post(
            "/api/orders",
            json={"cart_id": f"cart-{self.product_id}"},
            name="POST /api/orders",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 502):
                response.failure(f"order status={response.status_code}")
