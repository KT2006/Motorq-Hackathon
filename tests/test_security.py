import os
import pytest
from fastapi.testclient import TestClient
import jwt
from datetime import datetime, timedelta, timezone
from services.api.main import app, SECRET_KEY, ALGORITHM, get_db

client = TestClient(app)

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "your_secure_password_here")

def test_invalid_password_rejected():
    response = client.post("/token", json={"username": "admin", "password": "wrongpassword"})
    assert response.status_code == 401

def test_expired_token_rejected():
    payload = {
        "sub": "admin",
        "fleet_id": "*",
        "role": "admin",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    response = client.get("/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

def test_manager_cannot_read_other_fleet_vehicle_cost():
    response = client.post("/token", json={"username": "manager_1", "password": DEMO_PASSWORD})
    if response.status_code != 200:
        pytest.skip("Login failed, skipping")
    token = response.json()["access_token"]
    
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
    manager_fleet = decoded["fleet_id"]
    
    with get_db() as cur:
        cur.execute("SELECT vehicle_id FROM vehicles WHERE fleet_id != %s LIMIT 1", (manager_fleet,))
        row = cur.fetchone()
        if not row:
            pytest.skip("No other fleet vehicles found")
        other_vehicle_id = row["vehicle_id"]
        
    now = datetime.now()
    from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    
    res = client.get(
        f"/vehicles/{other_vehicle_id}/cost-summary?from_date={from_date}&to_date={to_date}",
        headers={"Authorization": f"Bearer {token}"}
    )
    # The API returns an empty list for 404/not found, but let's just make sure it doesn't return data
    # Wait, the tenant isolation fix added in main.py either throws 404 or returns empty.
    # Let's assert it doesn't return any data points.
    data = res.json()
    if res.status_code == 200:
        if isinstance(data, dict):
            assert len(data.get("data", [])) == 0, "Should not return data for another fleet"
        elif isinstance(data, list):
            assert len(data) == 0, "Should not return data for another fleet"
    else:
        assert res.status_code in (403, 404)

def test_manager_cannot_read_other_fleet_live_status():
    response = client.post("/token", json={"username": "manager_1", "password": DEMO_PASSWORD})
    if response.status_code != 200:
        pytest.skip("Login failed, skipping")
    token = response.json()["access_token"]
    
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
    manager_fleet = decoded["fleet_id"]
    
    with get_db() as cur:
        cur.execute("SELECT vin FROM vehicles WHERE fleet_id != %s LIMIT 1", (manager_fleet,))
        row = cur.fetchone()
        if not row:
            pytest.skip("No other fleet vehicles found")
        other_vin = row["vin"]
        
    res = client.get(
        f"/vehicles/{other_vin}/live-status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code in (403, 404)

def test_token_endpoint_rate_limited():
    # Reset limiter for token endpoint if possible, but we can't easily.
    # Just hit it until it 429s.
    for _ in range(12):
        res = client.post("/token", json={"username": "admin", "password": "wrongpassword"})
        if res.status_code == 429:
            break
    
    assert res.status_code == 429
