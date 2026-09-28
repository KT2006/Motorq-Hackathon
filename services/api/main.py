import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

import jwt
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ---------------------------------------------------------------------------
# Setup & Config
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

POSTGRES_URL = os.getenv("POSTGRES_URL", "")
SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-hackathon-key")
ALGORITHM = "HS256"

from fastapi.middleware.cors import CORSMiddleware

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Motorq Hackathon API - M7", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    logging.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)")
    return response

security = HTTPBearer()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@contextmanager
def get_db():
    if not POSTGRES_URL:
        raise RuntimeError("POSTGRES_URL not set in .env")
    url = POSTGRES_URL.replace("postgres://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        # Use RealDictCursor to return dicts instead of tuples
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Simple JWT verification."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/token")
def login(creds: LoginRequest):
    """Generates a test token valid for 1 hour."""
    # Use environment variables for demo credentials to avoid hardcoding secrets
    demo_user = os.getenv("DEMO_USERNAME", "admin")
    demo_pass = os.getenv("DEMO_PASSWORD")
    
    if not demo_pass or creds.username != demo_user or creds.password != demo_pass:
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    payload = {
        "sub": creds.username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/vehicles")
@limiter.limit("100/minute")
def list_vehicles(
    request: Request,
    fleet_id: Optional[str] = None,
    fuel_type: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(verify_token)
):
    """List vehicles with optional filtering and offset pagination."""
    query = "SELECT vehicle_id, vin, make, model, model_year, fuel_type, fleet_id FROM vehicles WHERE 1=1"
    params = []
    
    if fleet_id:
        query += " AND fleet_id = %s"
        params.append(fleet_id)
    if fuel_type:
        query += " AND fuel_type = %s"
        params.append(fuel_type)
        
    query += " ORDER BY vin LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    with get_db() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        
    return {"data": rows, "limit": limit, "offset": offset, "count": len(rows)}

@app.get("/vehicles/{vehicle_id}/cost-summary")
@limiter.limit("100/minute")
def vehicle_cost_summary(
    request: Request,
    vehicle_id: str,
    from_date: date,
    to_date: date,
    user: dict = Depends(verify_token)
):
    """Get daily cost breakdown for a specific vehicle over a date range."""
    try:
        UUID(vehicle_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Vehicle not found (invalid ID)")
        
    vehicle_id_str = vehicle_id
    query = """
        SELECT v.vin, cs.summary_date, cs.total_distance_km, cs.total_drive_min, cs.total_idle_min,
               fuel_cost, idle_cost, utilisation_pct
        FROM cost_summary_daily cs
        JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
        WHERE cs.vehicle_id = %s AND cs.summary_date BETWEEN %s AND %s
        ORDER BY cs.summary_date ASC
    """
    with get_db() as cur:
        cur.execute(query, (vehicle_id_str, from_date, to_date))
        rows = cur.fetchall()
        
    if not rows:
        raise HTTPException(status_code=404, detail="Vehicle not found or no data in date range")
        
    vin = rows[0].pop("vin")
    for row in rows[1:]:
        row.pop("vin", None)
    return {"vehicle_id": vehicle_id_str, "vin": vin, "data": rows}

@app.get("/fleet/summary")
@limiter.limit("100/minute")
def fleet_summary(
    request: Request,
    month: date = Query(..., description="First day of the month, e.g., 2026-08-01"),
    fleet_id: Optional[str] = None,
    user: dict = Depends(verify_token)
):
    """Headline cost numbers using the materialized view monthly_fleet_cost."""
    query = """
        SELECT SUM(total_fuel_cost) as total_fuel_cost,
               SUM(total_idle_cost) as total_idle_cost,
               AVG(avg_utilisation_pct) as avg_utilisation_pct,
               SUM(total_idle_min) as total_idle_min,
               SUM(vehicle_count) as total_vehicles
        FROM monthly_fleet_cost
        WHERE month = %s
    """
    params = [month]
    
    if fleet_id:
        query += " AND fleet_id = %s"
        params.append(fleet_id)
        
    with get_db() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        
    return {"month": month, "summary": row}

@app.get("/fleet/offenders")
@limiter.limit("100/minute")
def top_offenders(
    request: Request,
    from_date: date,
    to_date: date,
    limit: int = Query(10, le=100),
    user: dict = Depends(verify_token)
):
    """
    Top-K worst offenders by weighted score over a date range.
    Reuses the M5 scoring logic.
    """
    query = """
    WITH daily_scores AS (
        SELECT cs.vehicle_id, v.vin, v.fuel_type, cs.total_drive_min, cs.total_idle_min,
               cs.idle_cost, cs.fuel_cost, cs.utilisation_pct,
               CASE
                   WHEN (cs.total_drive_min + cs.total_idle_min) > 0 THEN
                       cs.total_idle_min / (cs.total_drive_min + cs.total_idle_min) * 100.0
                   ELSE 0.0
               END AS idle_pct_of_active
        FROM cost_summary_daily cs
        JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
        WHERE cs.summary_date BETWEEN %s AND %s
    ),
    vehicle_agg AS (
        SELECT vehicle_id, vin, fuel_type,
               ROUND(AVG(total_drive_min)::numeric, 1)  AS avg_drive_min,
               ROUND(AVG(total_idle_min)::numeric, 1)   AS avg_idle_min,
               ROUND(SUM(idle_cost)::numeric, 2)        AS total_idle_cost,
               ROUND(SUM(fuel_cost)::numeric, 2)        AS total_fuel_cost,
               ROUND(AVG(utilisation_pct)::numeric, 1)  AS avg_util_pct,
               ROUND(AVG(idle_pct_of_active)::numeric, 1) AS avg_idle_pct
        FROM daily_scores
        GROUP BY vehicle_id, vin, fuel_type
    ),
    scored AS (
        SELECT *,
               (
                   1.0 * (total_idle_cost / GREATEST(NULLIF((SELECT MAX(total_idle_cost) FROM vehicle_agg), 0), 1)) +
                   1.0 * (avg_idle_pct / 100.0) +
                   1.0 * (avg_idle_min / GREATEST(NULLIF((SELECT MAX(avg_idle_min) FROM vehicle_agg), 0), 1))
               ) AS weighted_score
        FROM vehicle_agg
    )
    SELECT * FROM scored
    ORDER BY weighted_score DESC
    LIMIT %s
    """
    with get_db() as cur:
        cur.execute(query, (from_date, to_date, limit))
        rows = cur.fetchall()
        
    return {"data": rows, "limit": limit}

import redis

redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(
    host=redis_host,
    port=redis_port,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
    health_check_interval=30,
)

@app.get("/health", include_in_schema=False)
def health_check():
    """Container health probe: both durable and live-status stores must be reachable."""
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        redis_client.ping()
        return {"status": "ok", "postgres": "ok", "redis": "ok"}
    except (psycopg2.Error, redis.RedisError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"Dependency unavailable: {exc}")

@app.get("/vehicles/{vin}/live-status")
@limiter.limit("100/minute")
def get_live_status(request: Request, vin: str, user: dict = Depends(verify_token)):
    """Fetch live, ephemeral vehicle status from Redis."""
    try:
        status = redis_client.hgetall(f"vehicle:{vin}:status")
        if not status:
            raise HTTPException(status_code=404, detail="No live status available for this vehicle")
        
        # Cast values for a polished response
        if 'speed_kmh' in status:
            status['speed_kmh'] = float(status['speed_kmh'])
        if 'ignition_status' in status:
            status['ignition_status'] = status['ignition_status'].lower() == 'true'
            
        return status
    except redis.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Redis cache unavailable")

# ---------------------------------------------------------------------------
# M9: AI Agent Layer
# ---------------------------------------------------------------------------
import json
import traceback
from pydantic import BaseModel
from openai import OpenAI

class ChatRequest(BaseModel):
    query: str
    from_date: str = "2026-08-28"
    to_date: str = "2026-09-26"

def run_agent_loop(query: str, from_date: str, to_date: str):
    # Using Groq's free API which is OpenAI-compatible
    api_key = os.getenv("GROQ_API_KEY", os.getenv("OPENAI_API_KEY", "dummy"))
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )
    
    # We'll use a supported model available for your API key
    model_name = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    
    # 1. Define tools
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_fleet_offenders",
                "description": "Get the top worst offending vehicles ranked by idle waste score.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of vehicles to return (max 50)"}
                    },
                    "required": ["limit"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_vehicle_cost_summary",
                "description": "Get daily cost breakdown (fuel and idle) for a specific vehicle.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vehicle_id": {"type": "string", "description": "The UUID of the vehicle"}
                    },
                    "required": ["vehicle_id"]
                }
            }
        }
    ]
    
    messages = [
        {"role": "system", "content": f"You are an AI fleet manager assistant. Answer questions using the provided tools. Today is {to_date}. Always refer to specific numbers and costs in your response."}
    ]
    messages.append({"role": "user", "content": query})
    
    max_loops = 5
    tool_calls_log = []
    
    for i in range(max_loops):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        msg = response.choices[0].message
        messages.append(msg)
        
        if not msg.tool_calls:
            # Model generated a final answer
            return msg.content, tool_calls_log
            
        # Execute tool calls
        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            tool_calls_log.append({"name": func_name, "args": args})
            
            try:
                if func_name == "get_fleet_offenders":
                    # Re-use our existing logic
                    # To avoid passing request object, we just call the inner logic or copy the query
                    limit = args.get("limit", 10)
                    with get_db() as cur:
                        cur.execute("""
                            WITH daily_scores AS (
                                SELECT cs.vehicle_id, v.vin, v.fuel_type, cs.total_drive_min, cs.total_idle_min,
                                       cs.idle_cost, cs.fuel_cost, cs.utilisation_pct,
                                       CASE WHEN (cs.total_drive_min + cs.total_idle_min) > 0 THEN cs.total_idle_min / (cs.total_drive_min + cs.total_idle_min) * 100.0 ELSE 0.0 END AS idle_pct_of_active
                                FROM cost_summary_daily cs JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
                                WHERE cs.summary_date BETWEEN %s AND %s
                            ),
                            vehicle_agg AS (
                                SELECT vehicle_id, vin, fuel_type, ROUND(AVG(total_drive_min)::numeric, 1) AS avg_drive_min, ROUND(AVG(total_idle_min)::numeric, 1) AS avg_idle_min,
                                       ROUND(SUM(idle_cost)::numeric, 2) AS total_idle_cost, ROUND(SUM(fuel_cost)::numeric, 2) AS total_fuel_cost,
                                       ROUND(AVG(utilisation_pct)::numeric, 1) AS avg_util_pct, ROUND(AVG(idle_pct_of_active)::numeric, 1) AS avg_idle_pct
                                FROM daily_scores GROUP BY vehicle_id, vin, fuel_type
                            ),
                            scored AS (
                                SELECT *, (1.0 * (total_idle_cost / GREATEST(NULLIF((SELECT MAX(total_idle_cost) FROM vehicle_agg), 0), 1)) + 1.0 * (avg_idle_pct / 100.0) + 1.0 * (avg_idle_min / GREATEST(NULLIF((SELECT MAX(avg_idle_min) FROM vehicle_agg), 0), 1))) AS weighted_score
                                FROM vehicle_agg
                            )
                            SELECT * FROM scored ORDER BY weighted_score DESC LIMIT %s
                        """, (from_date, to_date, limit))
                        result = cur.fetchall()
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result, default=str)})
                    
                elif func_name == "get_vehicle_cost_summary":
                    vehicle_id = args.get("vehicle_id")
                    with get_db() as cur:
                        cur.execute("""
                            SELECT summary_date, total_distance_km, total_drive_min, total_idle_min, fuel_cost, idle_cost, utilisation_pct
                            FROM cost_summary_daily WHERE vehicle_id = %s AND summary_date BETWEEN %s AND %s ORDER BY summary_date ASC
                        """, (vehicle_id, from_date, to_date))
                        result = cur.fetchall()
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result, default=str)})
                else:
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": "Error: Unknown tool."})
            except Exception as e:
                # Graceful failure
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": f"Error retrieving data: {str(e)}"})
                
    return "I couldn't complete the analysis in time. Please try asking a simpler question.", tool_calls_log

@app.post("/chat")
@limiter.limit("20/minute")
def chat_with_agent(
    request: Request,
    payload: ChatRequest,
    user: dict = Depends(verify_token)
):
    if not os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY or OPENAI_API_KEY not configured on server")
        
    try:
        final_answer, tool_calls = run_agent_loop(payload.query, payload.from_date, payload.to_date)
        
        # Write to audit log
        with get_db() as cur:
            cur.execute("""
                INSERT INTO agent_logs (user_question, tool_calls_json, final_answer)
                VALUES (%s, %s, %s)
            """, (payload.query, json.dumps(tool_calls), final_answer))
            cur.connection.commit()
            
        return {
            "query": payload.query,
            "answer": final_answer,
            "tool_calls": tool_calls
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
