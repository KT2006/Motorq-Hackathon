const API_BASE = 'http://127.0.0.1:8000';

let token = null;

// Get a token to use for testing
export const initAuth = async () => {
  if (token) return token;
  try {
    const res = await fetch(`${API_BASE}/token`, { method: 'POST' });
    const data = await res.json();
    token = data.access_token;
    return token;
  } catch (err) {
    console.error("Auth init failed:", err);
    return null;
  }
};

const fetchAPI = async (endpoint) => {
  await initAuth();
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
};

export const getFleetSummary = (month = '2026-08-01') => {
  return fetchAPI(`/fleet/summary?month=${month}`);
};

export const getTopOffenders = (limit = 10, from = '2026-08-28', to = '2026-09-26') => {
  return fetchAPI(`/fleet/offenders?limit=${limit}&from_date=${from}&to_date=${to}`);
};

export const getVehicleCostSummary = (vehicleId, from = '2026-08-28', to = '2026-09-26') => {
  return fetchAPI(`/vehicles/${vehicleId}/cost-summary?from_date=${from}&to_date=${to}`);
};
