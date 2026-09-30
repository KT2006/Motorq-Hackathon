import json
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
SECRET_KEY = os.getenv("JWT_SECRET", "")
ALGORITHM = "HS256"

from fastapi.middleware.cors import CORSMiddleware

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Motorq Hackathon API - M7", version="1.0.0")

# In production, restrict to the actual dashboard origin.
# For the Docker Compose submission, the dashboard proxies through nginx
# on the same origin, so CORS is only needed for local dev.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:80,http://localhost:5173,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

@app.on_event("startup")
async def _check_config():
    if not SECRET_KEY:
        logging.warning("JWT_SECRET not set — authentication will reject all tokens")

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

def get_fleet_filter(user: dict) -> Optional[str]:
    """Return the fleet_id from the JWT, or None if admin (*) access."""
    fid = user.get("fleet_id", "*")
    return None if fid == "*" else fid

def audit_log(user: dict, action: str, resource: str, resource_id: str = None, 
              details: dict = None, ip: str = None):
    """Write a structured audit event for sensitive data access."""
    try:
        with get_db() as cur:
            cur.execute("""
                INSERT INTO audit_log (user_sub, action, resource, resource_id, ip_address, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user.get("sub", "unknown"), action, resource, resource_id, ip, 
                  json.dumps(details) if details else None))
            cur.connection.commit()
    except Exception as e:
        logging.warning("audit_log_failed: %s", e)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/token")
@limiter.limit("10/minute")
def login(request: Request, creds: LoginRequest):
    """Generates a test token valid for 1 hour."""
    # Use environment variables for demo credentials to avoid hardcoding secrets
    demo_user = os.getenv("DEMO_USERNAME", "admin")
    demo_pass = os.getenv("DEMO_PASSWORD", "changeme")
    
    if creds.password != demo_pass:
        raise HTTPException(status_code=401, detail="Invalid password")
        
    if creds.username == demo_user:
        fleet_id = "*"
        role = "admin"
    elif creds.username in ("manager_1", "manager_2"):
        # For demo purposes, map these two explicit test users to the first two seeded fleets
        try:
            idx = 0 if creds.username == "manager_1" else 1
            
            with get_db() as cur:
                cur.execute("SELECT fleet_id FROM fleets ORDER BY fleet_id ASC OFFSET %s LIMIT 1", (idx,))
                row = cur.fetchone()
                fleet_id = str(row["fleet_id"]) if row else "unknown-fleet"
        except Exception:
            fleet_id = "unknown-fleet"
        role = "manager"
    else:
        raise HTTPException(status_code=401, detail="Invalid username")
        
    payload = {
        "sub": creds.username,
        "fleet_id": fleet_id,
        "role": role,
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
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor (vin)"),
    user: dict = Depends(verify_token)
):
    """List vehicles with keyset pagination."""
    query = "SELECT vehicle_id, vin, make, model, model_year, fuel_type, fleet_id FROM vehicles WHERE 1=1"
    params = []
    
    fleet_id_filter = get_fleet_filter(user)
    if fleet_id_filter:
        query += " AND fleet_id = %s"
        params.append(fleet_id_filter)

    if fleet_id and not fleet_id_filter:
        query += " AND fleet_id = %s"
        params.append(fleet_id)
    if fuel_type:
        query += " AND fuel_type = %s"
        params.append(fuel_type)
        
    if cursor:
        query += " AND vin > %s"
        params.append(cursor)
        
    query += " ORDER BY vin ASC LIMIT %s"
    params.append(limit)
    
    with get_db() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        
    return {"data": rows, "limit": limit, "cursor": cursor, "count": len(rows)}

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
    audit_log(user, "read", "vehicle_cost", vehicle_id, ip=request.client.host)
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
    """
    params = [vehicle_id_str, from_date, to_date]
    
    fleet_id_filter = get_fleet_filter(user)
    if fleet_id_filter:
        query += " AND v.fleet_id = %s"
        params.append(fleet_id_filter)
        
    query += " ORDER BY cs.summary_date ASC"

    with get_db() as cur:
        cur.execute(query, tuple(params))
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
    fleet_id_filter = get_fleet_filter(user)
    
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
    
    if fleet_id_filter:
        query += " AND fleet_id = %s"
        params.append(fleet_id_filter)
    elif fleet_id:
        query += " AND fleet_id = %s"
        params.append(fleet_id)
        
    with get_db() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        
    return {
        "month": month.isoformat(),
        "total_fuel_cost": float(row["total_fuel_cost"] or 0),
        "total_idle_cost": float(row["total_idle_cost"] or 0),
        "avg_utilisation_pct": float(row["avg_utilisation_pct"] or 0),
        "total_idle_min": float(row["total_idle_min"] or 0),
        "total_vehicles": int(row["total_vehicles"] or 0),
    }

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
    fleet_id_filter = get_fleet_filter(user)
    params = [from_date, to_date]
    fleet_clause = ""
    if fleet_id_filter:
        fleet_clause = "AND v.fleet_id = %s"
        params.append(fleet_id_filter)

    query = f"""
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
        {fleet_clause}
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
    params.append(limit)
    with get_db() as cur:
        cur.execute(query, tuple(params))
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
    audit_log(user, "read", "live_status", vin, ip=request.client.host)
    
    fleet_id_filter = get_fleet_filter(user)
    if fleet_id_filter:
        with get_db() as cur:
            cur.execute("SELECT 1 FROM vehicles WHERE vin = %s AND fleet_id = %s", (vin, fleet_id_filter))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Vehicle not found in your fleet")

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
    from_date: str = Field(default_factory=lambda: (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))

def run_agent_loop(query: str, from_date: str, to_date: str, user: dict):
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
    
    agent_start = time.time()
    MAX_AGENT_SECONDS = 30
    
    for i in range(max_loops):
        if time.time() - agent_start > MAX_AGENT_SECONDS:
            return "Analysis timed out. Please try a simpler question.", tool_calls_log

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                timeout=15,
            )
        except Exception as llm_err:
            logging.error("LLM API call failed: %s", llm_err)
            return f"I'm unable to connect to the AI service right now. Error: {str(llm_err)}", tool_calls_log

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
                    limit = min(max(1, int(args.get("limit", 10))), 50)
                    fleet_id_filter = get_fleet_filter(user)
                    fleet_clause = ""
                    params = [from_date, to_date]
                    if fleet_id_filter:
                        fleet_clause = "AND v.fleet_id = %s"
                        params.append(fleet_id_filter)
                    params.append(limit)

                    with get_db() as cur:
                        cur.execute(f"""
                            WITH daily_scores AS (
                                SELECT cs.vehicle_id, v.vin, v.fuel_type, cs.total_drive_min, cs.total_idle_min,
                                       cs.idle_cost, cs.fuel_cost, cs.utilisation_pct,
                                       CASE WHEN (cs.total_drive_min + cs.total_idle_min) > 0 THEN cs.total_idle_min / (cs.total_drive_min + cs.total_idle_min) * 100.0 ELSE 0.0 END AS idle_pct_of_active
                                FROM cost_summary_daily cs JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
                                WHERE cs.summary_date BETWEEN %s AND %s
                                {fleet_clause}
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
                        """, tuple(params))
                        result = cur.fetchall()
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result, default=str)})
                    
                elif func_name == "get_vehicle_cost_summary":
                    vehicle_id = args.get("vehicle_id")
                    fleet_id_filter = get_fleet_filter(user)
                    query = """
                        SELECT cs.summary_date, cs.total_distance_km, cs.total_drive_min, cs.total_idle_min, cs.fuel_cost, cs.idle_cost, cs.utilisation_pct
                        FROM cost_summary_daily cs
                        JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
                        WHERE cs.vehicle_id = %s AND cs.summary_date BETWEEN %s AND %s
                    """
                    params = [vehicle_id, from_date, to_date]
                    if fleet_id_filter:
                        query += " AND v.fleet_id = %s"
                        params.append(fleet_id_filter)
                    query += " ORDER BY cs.summary_date ASC"

                    with get_db() as cur:
                        cur.execute(query, tuple(params))
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
    audit_log(user, "ai_query", "chat", details={"query": payload.query}, ip=request.client.host)
    if not os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY or OPENAI_API_KEY not configured on server")
        
    try:
        final_answer, tool_calls = run_agent_loop(payload.query, payload.from_date, payload.to_date, user)
        
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
