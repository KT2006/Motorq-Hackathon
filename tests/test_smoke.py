import os
import pytest
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEMO_USERNAME = os.getenv("DEMO_USERNAME", "admin")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "changeme")

def is_server_running():
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not is_server_running(), reason=f"Server not running at {API_BASE_URL}")
]

class TestSmokeJourney:
    
    def test_health_check(self):
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        assert response.status_code == 200

    def test_judge_journey(self):
        # 1. Authenticate via /token
        auth_response = requests.post(
            f"{API_BASE_URL}/token",
            json={"username": DEMO_USERNAME, "password": DEMO_PASSWORD},
            timeout=5
        )
        assert auth_response.status_code == 200, f"Auth failed: {auth_response.text}"
        
        token = auth_response.json().get("access_token")
        assert token is not None, "No access token in response"
        headers = {"Authorization": f"Bearer {token}"}

        now = datetime.now()
        from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        # 2. Call /fleet/summary using its latest-data-month default.
        summary_response = requests.get(
            f"{API_BASE_URL}/fleet/summary",
            headers=headers,
            timeout=5
        )
        assert summary_response.status_code == 200, f"Fleet summary failed: {summary_response.text}"
        summary_data = summary_response.json()
        assert summary_data.get("total_vehicles", 0) > 0, "Expected total_vehicles > 0"

        # 3. Call /fleet/offenders
        offenders_response = requests.get(
            f"{API_BASE_URL}/fleet/offenders?from_date={from_date}&to_date={to_date}&limit=10",
            headers=headers,
            timeout=5
        )
        assert offenders_response.status_code == 200, f"Fleet offenders failed: {offenders_response.text}"
        offenders = offenders_response.json()
        assert len(offenders.get("data", [])) > 0, "Expected at least one offender"
        
        first_offender = offenders["data"][0]
        assert first_offender.get("weighted_score", 0) > 0, "Expected weighted_score > 0"
        
        vehicle_id = first_offender.get("vehicle_id")
        assert vehicle_id is not None, "Offender missing vehicle_id"

        # 4. Call /vehicles/<vehicle_id>/cost-summary
        cost_response = requests.get(
            f"{API_BASE_URL}/vehicles/{vehicle_id}/cost-summary?from_date={from_date}&to_date={to_date}",
            headers=headers,
            timeout=5
        )
        assert cost_response.status_code == 200, f"Cost summary failed: {cost_response.text}"
        cost_summary = cost_response.json()
        
        # 5. Assert cost summary returns data with fuel_cost and idle_cost fields
        # Check based on whether it's a dict summary or a list of records
        if isinstance(cost_summary, dict) and "data" in cost_summary and len(cost_summary["data"]) > 0:
            first_cost = cost_summary["data"][0]
            assert "fuel_cost" in first_cost, "fuel_cost missing in cost summary record"
            assert "idle_cost" in first_cost, "idle_cost missing in cost summary record"
        elif isinstance(cost_summary, list) and len(cost_summary) > 0:
            first_cost = cost_summary[0]
            assert "fuel_cost" in first_cost, "fuel_cost missing in cost summary record"
            assert "idle_cost" in first_cost, "idle_cost missing in cost summary record"
        else:
            pytest.fail(f"Unexpected cost summary format or empty: {cost_summary}")
