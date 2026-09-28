const API_BASE = 'http://127.0.0.1:8000';

let token = null;

export const initAuth = async () => {
  if (token) return token;
  try {
    const res = await fetch(`${API_BASE}/token`, { 
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'MtrQ_Admin2026!' })
    });
    const data = await res.json();
    token = data.access_token;
    return token;
  } catch (err) {
    console.error("Auth init failed:", err);
    return null;
  }
};

const fetchAPI = async (endpoint, options = {}) => {
  await initAuth();
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`
    }
  });
  if (!res.ok) {
      let errDetail = `API error: ${res.status}`;
      try {
          const errBody = await res.json();
          if (errBody.detail) errDetail = errBody.detail;
      } catch (e) {}
      const error = new Error(errDetail);
      error.response = { data: { detail: errDetail } };
      throw error;
  }
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

const post = (endpoint, data) => {
    return fetchAPI(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).then(res => ({ data: res }));
};

export default { post };
