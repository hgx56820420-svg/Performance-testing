import random
import uuid

from locust import HttpUser, between, task


class MallUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.user_id = str(uuid.uuid4())
        self.product_id = random.randint(1, 100)
        self.cart_id = None

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
                return
            if not isinstance(response.json().get("items"), list):
                response.failure("catalog items is not a list")

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
                return
            if not isinstance(response.json().get("items"), list):
                response.failure("search items is not a list")

    @task(25)
    def view_detail(self):
        with self.client.get(
            f"/api/products/{self.product_id}",
            name="GET /api/products/{id}",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            # The generated product id is valid. A 404 is a test failure here;
            # negative-resource coverage belongs in a separate scenario.
            if response.status_code != 200:
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
                return
            payload = response.json()
            self.cart_id = payload.get("cart_id")
            if not self.cart_id:
                response.failure("cart_id missing from cart response")

    @task(8)
    def checkout(self):
        if not self.cart_id:
            # Do not send a synthetic order. This keeps the order metric tied to
            # a real cart created by this virtual user.
            return
        with self.client.post(
            "/api/orders",
            json={"cart_id": self.cart_id},
            name="POST /api/orders",
            headers={"X-User-Id": self.user_id},
            catch_response=True,
        ) as response:
            # A payment/downstream 502 is a business failure for this flow.
            if response.status_code != 200:
                response.failure(f"order status={response.status_code}")
                return
            if response.json().get("status") != "paid":
                response.failure("order status is not paid")
