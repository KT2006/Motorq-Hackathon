// VITE_API_BASE is injected at build time via docker-compose build args.
// Falls back to /api which is reverse-proxied by nginx to http://api:8000.
const API_BASE = import.meta.env.VITE_API_BASE || '/api';

const TOKEN_KEY = 'motorq_token';

// ── Token helpers ────────────────────────────────────────────────────────────

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

const saveToken = (t) => localStorage.setItem(TOKEN_KEY, t);

// ── Auth ─────────────────────────────────────────────────────────────────────

/**
 * Exchange username + password for a JWT and persist it in localStorage.
 * Called from the Login page. Throws on failure so the form can show an error.
 */
export const loginWithCredentials = async (username, password) => {
  const res = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Login failed (${res.status})`);
  }
  const data = await res.json();
  saveToken(data.access_token);
  return data.access_token;
};

// ── Core fetch wrapper ───────────────────────────────────────────────────────

const fetchAPI = async (endpoint, options = {}) => {
  const token = getToken();
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      ...options.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  // Token expired or revoked → clear it so App re-renders the login screen
  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new Event('motorq:unauthorized'));
    throw new Error('Session expired. Please log in again.');
  }

  if (!res.ok) {
    let errDetail = `API error: ${res.status}`;
    try {
      const errBody = await res.json();
      if (errBody.detail) errDetail = errBody.detail;
    } catch (_) { /* ignore */ }
    const error = new Error(errDetail);
    error.response = { data: { detail: errDetail } };
    throw error;
  }
  return res.json();
};

// ── Date helpers ─────────────────────────────────────────────────────────────

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

// ── API methods ──────────────────────────────────────────────────────────────

export const getFleetSummary = (month) =>
  fetchAPI(`/fleet/summary${month ? `?month=${encodeURIComponent(month)}` : ''}`);

export const getTopOffenders = (limit = 25, from = daysAgo(7), to = today(), offset = 0) =>
  fetchAPI(`/fleet/offenders?limit=${limit}&offset=${offset}&from_date=${from}&to_date=${to}`);

export const getVehicleCostSummary = (vehicleId, from = daysAgo(7), to = today()) =>
  fetchAPI(`/vehicles/${vehicleId}/cost-summary?from_date=${from}&to_date=${to}`);

export const getLiveStatus = (vin) =>
  fetchAPI(`/vehicles/${encodeURIComponent(vin)}/live-status`);

const post = (endpoint, data) =>
  fetchAPI(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then((res) => ({ data: res }));

export default { post };
