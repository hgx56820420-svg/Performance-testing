"""Read-only smoke scenario for the YY Game Mall QA environment.

This file deliberately avoids login, order, payment, publish, bargain and other
state-changing endpoints. The public API host is discovered from the page's
frontend bundle and can be overridden for a different QA deployment.
"""

import os

from locust import HttpUser, between, task

TARGET_ORIGIN = os.getenv("TARGET_ORIGIN", "https://gamesrv-qa.yy.com").rstrip("/")
MALL_PATH = os.getenv("MALL_PATH", "/proxy/mall/")
QA_API_BASE = os.getenv("QA_API_BASE", "https://test-gamemarket.yy.com").rstrip("/")


class QaMallPageUser(HttpUser):
    """Measures the HTML entry page only; Locust does not execute its JS assets."""

    host = TARGET_ORIGIN
    weight = 3
    wait_time = between(2, 5)

    @task
    def open_mall_home(self):
        with self.client.get(
            MALL_PATH,
            name="GET /proxy/mall/ (HTML)",
            headers={"Accept": "text/html,application/xhtml+xml"},
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
            elif "<html" not in response.text.lower():
                response.failure("HTML shell marker missing")


class QaMallAnonymousApiUser(HttpUser):
    """Measures GET endpoints verified to work without login or a signature."""

    host = QA_API_BASE
    weight = 1
    wait_time = between(2, 5)

    def _get_category_list(self, path: str, name: str):
        with self.client.get(
            f"{QA_API_BASE}{path}",
            name=name,
            headers={"Accept": "application/json, text/plain, */*"},
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
                return
            try:
                payload = response.json()
            except ValueError:
                response.failure("response is not JSON")
                return
            if payload.get("code") != 0 or not isinstance(payload.get("data"), list):
                response.failure(f"business code={payload.get('code')}")

    @task(4)
    def query_sub_categories(self):
        self._get_category_list(
            "/category/querySubCategories",
            "GET /category/querySubCategories (anonymous)",
        )

    @task(2)
    def query_categories(self):
        self._get_category_list(
            "/category/queryCategories",
            "GET /category/queryCategories (anonymous)",
        )

    @task(2)
    def query_show_categories(self):
        self._get_category_list(
            "/category/queryShowCategories",
            "GET /category/queryShowCategories (anonymous)",
        )

    @task(1)
    def query_show_sub_categories(self):
        self._get_category_list(
            "/category/queryShowSubCategories",
            "GET /category/queryShowSubCategories (anonymous)",
        )
