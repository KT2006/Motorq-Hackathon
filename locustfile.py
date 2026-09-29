"""Locust load test for the Fleet Intelligence API.

Usage:
    locust -f locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 10 --run-time 60s --headless
"""

import os
from datetime import date, timedelta
from locust import HttpUser, task, between


class FleetAPIUser(HttpUser):
    wait_time = between(0.5, 2)
    token = None

    def on_start(self):
        """Authenticate once per simulated user."""
        resp = self.client.post("/token", json={
            "username": os.getenv("DEMO_USERNAME", "admin"),
            "password": os.getenv("DEMO_PASSWORD", "changeme"),
        })
        if resp.status_code == 200:
            self.token = resp.json()["access_token"]
        else:
            self.token = ""

    @property
    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def fleet_summary(self):
        month = date.today().replace(day=1).isoformat()
        self.client.get(f"/fleet/summary?month={month}", headers=self.auth_headers)

    @task(5)
    def top_offenders(self):
        to_date = date.today().isoformat()
        from_date = (date.today() - timedelta(days=30)).isoformat()
        self.client.get(
            f"/fleet/offenders?from_date={from_date}&to_date={to_date}&limit=10",
            headers=self.auth_headers,
        )

    @task(2)
    def list_vehicles(self):
        self.client.get("/vehicles?limit=20", headers=self.auth_headers)

    @task(1)
    def health_check(self):
        self.client.get("/health")
