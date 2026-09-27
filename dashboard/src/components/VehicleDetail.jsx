import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getVehicleCostSummary } from '../api';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { ArrowLeft, Clock, MapPin, Fuel } from 'lucide-react';

export default function VehicleDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getVehicleCostSummary(id).then(res => {
      setData(res.data);
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

  // Format data for chart
  const chartData = data.map(d => ({
    name: new Date(d.summary_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    'Fuel Cost (₹)': d.fuel_cost,
    'Idle Cost (₹)': d.idle_cost
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

      <div className="kpi-grid">
        <div className="glass-panel">
          <div className="kpi-label">30-Day Idle Cost</div>
          <div className="kpi-value text-danger">₹{totalIdleCost.toLocaleString(undefined, {maximumFractionDigits:0})}</div>
        </div>
        <div className="glass-panel">
          <div className="kpi-label">30-Day Fuel Cost</div>
          <div className="kpi-value">₹{totalFuelCost.toLocaleString(undefined, {maximumFractionDigits:0})}</div>
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
              <Bar dataKey="Fuel Cost (₹)" stackId="a" fill="#3b82f6" />
              <Bar dataKey="Idle Cost (₹)" stackId="a" fill="#ef4444" />
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
                  <td className="text-danger">₹{day.idle_cost.toFixed(2)}</td>
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
