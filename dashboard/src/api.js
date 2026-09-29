// VITE_API_BASE is injected at build time via docker-compose build args.
// Falls back to /api which is reverse-proxied by nginx to http://api:8000.
// This means the dashboard works both locally (direct) and in any deployed env.
const API_BASE = import.meta.env.VITE_API_BASE || '/api';

let token = null;

export const initAuth = async () => {
  if (token) return token;
  try {
    const res = await fetch(`${API_BASE}/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: import.meta.env.VITE_DEMO_USERNAME || 'admin',
        password: import.meta.env.VITE_DEMO_PASSWORD
      })
    });
    const data = await res.json();
    token = data.access_token;
    return token;
  } catch (err) {
    console.error('Auth init failed:', err);
    return null;
  }
};

const fetchAPI = async (endpoint, options = {}) => {
  await initAuth();
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`
    }
  });
  if (!res.ok) {
    let errDetail = `API error: ${res.status}`;
    try {
      const errBody = await res.json();
      if (errBody.detail) errDetail = errBody.detail;
    } catch (e) { /* ignore */ }
    const error = new Error(errDetail);
    error.response = { data: { detail: errDetail } };
    throw error;
  }
  return res.json();
};

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`; };

export const getFleetSummary = (month = monthStart()) =>
  fetchAPI(`/fleet/summary?month=${month}`);

export const getTopOffenders = (limit = 10, from = daysAgo(30), to = today()) =>
  fetchAPI(`/fleet/offenders?limit=${limit}&from_date=${from}&to_date=${to}`);

export const getVehicleCostSummary = (vehicleId, from = daysAgo(30), to = today()) =>
  fetchAPI(`/vehicles/${vehicleId}/cost-summary?from_date=${from}&to_date=${to}`);

/** Fetch live ephemeral vehicle status from Redis via the API (polyglot store demo). */
export const getLiveStatus = (vin) =>
  fetchAPI(`/vehicles/${encodeURIComponent(vin)}/live-status`);

const post = (endpoint, data) =>
  fetchAPI(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).then(res => ({ data: res }));

export default { post };
