import { useEffect, useState } from 'react';
import { getFleetSummary } from '../api';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Activity, AlertTriangle, Fuel, DollarSign } from 'lucide-react';

export default function Overview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getFleetSummary().then(res => {
      setData(res);
      setLoading(false);
    }).catch(err => {
      console.error(err);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="loading-spinner"></div>;
  if (!data) return <div>Error loading data.</div>;

  const totalCost = data.total_fuel_cost + data.total_idle_cost;
  const idlePct = ((data.total_idle_cost / totalCost) * 100).toFixed(1);

  const chartData = [
    { name: 'Fuel (Driving)', value: data.total_fuel_cost, color: '#3b82f6' },
    { name: 'Idle Waste', value: data.total_idle_cost, color: '#ef4444' }
  ];

  return (
    <div className="animate-fade-in">
      <div className="flex-between mb-8">
        <div>
          <h1>Fleet Overview</h1>
          <p className="subtitle">Real-time cost analysis and utilisation metrics</p>
        </div>
      </div>

      <div className="kpi-grid">
        <div className="glass-panel">
          <div className="flex-between text-muted">
            <span className="kpi-label">Total Idle Waste (Aug)</span>
            <AlertTriangle size={20} className="text-danger" />
          </div>
          <div className="kpi-value kpi-danger">
            ₹{data.total_idle_cost.toLocaleString(undefined, {maximumFractionDigits:0})}
          </div>
          <p className="text-muted">
            <span className="text-danger font-bold">{idlePct}%</span> of total fleet fuel costs
          </p>
        </div>

        <div className="glass-panel">
          <div className="flex-between text-muted">
            <span className="kpi-label">Total Fleet Cost</span>
            <DollarSign size={20} className="text-muted" />
          </div>
          <div className="kpi-value">
            ₹{totalCost.toLocaleString(undefined, {maximumFractionDigits:0})}
          </div>
          <p className="text-muted">Across {data.total_vehicles} vehicles</p>
        </div>

        <div className="glass-panel">
          <div className="flex-between text-muted">
            <span className="kpi-label">Avg Utilisation</span>
            <Activity size={20} className="text-success" />
          </div>
          <div className="kpi-value" style={{ background: 'linear-gradient(to right, #10b981, #34d399)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            {data.avg_utilisation_pct.toFixed(1)}%
          </div>
          <p className="text-muted">Active driving time vs total available</p>
        </div>
      </div>

      <div className="glass-panel">
        <h2>Cost Breakdown</h2>
        <div className="chart-container" style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={80}
                outerRadius={120}
                paddingAngle={5}
                dataKey="value"
                stroke="none"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip 
                formatter={(value) => `₹${value.toLocaleString(undefined, {maximumFractionDigits:0})}`}
                contentStyle={{ background: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff' }}
              />
              <Legend verticalAlign="bottom" height={36}/>
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
