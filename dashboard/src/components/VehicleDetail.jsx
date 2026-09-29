import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { getVehicleCostSummary, getLiveStatus } from '../api';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { ArrowLeft, Radio } from 'lucide-react';

/** Poll an API function every `intervalMs` ms. Returns { data, error, loading }. */
function usePolling(fetcher, intervalMs = 5000) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await fetcher();
        if (!cancelled) setState({ data: result, error: null, loading: false });
      } catch (err) {
        if (!cancelled) setState(s => ({ ...s, error: err.message, loading: false }));
      }
      if (!cancelled) timerRef.current = setTimeout(poll, intervalMs);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timerRef.current);
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  return state;
}

/** Live status card — shows Redis-cached position/speed, updates every 5s. */
function LiveStatusCard({ vin }) {
  const { data, error, loading } = usePolling(() => getLiveStatus(vin), 5000);

  const statusStyle = {
    background: 'linear-gradient(135deg, rgba(16,185,129,0.12), rgba(16,185,129,0.04))',
    border: '1px solid rgba(16,185,129,0.3)',
    borderRadius: 12,
    padding: '20px 24px',
    marginBottom: 24,
  };
  const dotStyle = (on) => ({
    display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
    background: on ? '#10b981' : '#ef4444',
    marginRight: 8,
    animation: on ? 'pulse 2s infinite' : 'none',
  });

  if (loading) {
    return (
      <div style={statusStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'rgba(255,255,255,0.5)' }}>
          <Radio size={16} /> Live Status — connecting…
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={statusStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'rgba(255,255,255,0.4)' }}>
          <span style={dotStyle(false)} />
          Live Status — no stream data yet
          <span style={{ fontSize: 12, opacity: 0.6 }}>(start the ingestion stream to see updates)</span>
        </div>
      </div>
    );
  }

  const ign = data.ignition_status === true || data.ignition_status === 'true';
  const speed = parseFloat(data.speed_kmh || 0).toFixed(1);
  const lat = parseFloat(data.lat || 0).toFixed(5);
  const lon = parseFloat(data.lon || 0).toFixed(5);
  const lastSeen = data.last_seen ? new Date(data.last_seen).toLocaleTimeString() : '—';

  return (
    <div style={statusStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Radio size={16} style={{ color: '#10b981' }} />
        <span style={{ fontWeight: 600, fontSize: 14, color: '#10b981' }}>
          Live Status
        </span>
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginLeft: 4 }}>
          (updates every 5s · source: Redis)
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>Ignition</div>
          <div style={{ fontWeight: 600 }}>
            <span style={dotStyle(ign)} />
            {ign ? 'ON' : 'OFF'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>Speed</div>
          <div style={{ fontWeight: 600 }}>{speed} km/h</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>Position</div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{lat}, {lon}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>Last Seen</div>
          <div style={{ fontWeight: 600 }}>{lastSeen}</div>
        </div>
      </div>
    </div>
  );
}

export default function VehicleDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [vin, setVin] = useState(location.state?.vin || null);

  useEffect(() => {
    getVehicleCostSummary(id).then(res => {
      setData(res.data);
      setVin(res.vin);
      setLoading(false);
    }).catch(err => {
      console.error(err);
      setLoading(false);
    });
  }, [id]);

  if (loading) return <div className="loading-spinner"></div>;
  if (!data || data.length === 0) return <div>No data found for this vehicle.</div>;

  const totalFuelCost = data.reduce((sum, day) => sum + day.fuel_cost, 0);
  const totalIdleCost = data.reduce((sum, day) => sum + day.idle_cost, 0);
  const avgUtil = (data.reduce((sum, day) => sum + day.utilisation_pct, 0) / data.length).toFixed(1);

  const chartData = data.map(d => ({
    name: new Date(d.summary_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    'Fuel Cost (Rs)': d.fuel_cost,
    'Idle Cost (Rs)': d.idle_cost
  }));

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => navigate('/leaderboard')}
        style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '24px' }}
      >
        <ArrowLeft size={16} /> Back to Leaderboard
      </button>

      <div className="flex-between mb-8">
        <div>
          <h1>Vehicle Analysis</h1>
          <p className="subtitle">ID: {id}</p>
        </div>
      </div>

      {/* Live Status Card — polls Redis every 5s */}
      {vin && <LiveStatusCard vin={vin} />}

      <div className="kpi-grid">
        <div className="glass-panel">
          <div className="kpi-label">30-Day Idle Cost</div>
          <div className="kpi-value text-danger">Rs{totalIdleCost.toLocaleString(undefined, {maximumFractionDigits:0})}</div>
        </div>
        <div className="glass-panel">
          <div className="kpi-label">30-Day Fuel Cost</div>
          <div className="kpi-value">Rs{totalFuelCost.toLocaleString(undefined, {maximumFractionDigits:0})}</div>
        </div>
        <div className="glass-panel">
          <div className="kpi-label">Avg Daily Utilisation</div>
          <div className="kpi-value text-success">{avgUtil}%</div>
        </div>
      </div>

      <div className="glass-panel mb-8">
        <h2>Daily Cost Trend</h2>
        <div className="chart-container">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="name" stroke="rgba(255,255,255,0.5)" />
              <YAxis stroke="rgba(255,255,255,0.5)" />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff' }}
              />
              <Legend />
              <Bar dataKey="Fuel Cost (Rs)" stackId="a" fill="#3b82f6" />
              <Bar dataKey="Idle Cost (Rs)" stackId="a" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="glass-panel">
        <h2>Detailed Daily Log</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Distance (km)</th>
                <th>Drive Time (min)</th>
                <th>Idle Time (min)</th>
                <th>Idle Cost</th>
                <th>Utilisation</th>
              </tr>
            </thead>
            <tbody>
              {data.map((day) => (
                <tr key={day.summary_date}>
                  <td>{new Date(day.summary_date).toLocaleDateString()}</td>
                  <td>{day.total_distance_km.toFixed(1)}</td>
                  <td>{day.total_drive_min.toFixed(1)}</td>
                  <td className={day.total_idle_min > 60 ? 'text-danger' : ''}>{day.total_idle_min.toFixed(1)}</td>
                  <td className="text-danger">Rs{day.idle_cost.toFixed(2)}</td>
                  <td>{day.utilisation_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
