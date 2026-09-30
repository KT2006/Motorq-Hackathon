import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getTopOffenders } from '../api';
import { AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { formatINR } from '../formatters';

export default function Leaderboard() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sortConfig, setSortConfig] = useState({ key: 'weighted_score', direction: 'desc' });
  const navigate = useNavigate();

  useEffect(() => {
    getTopOffenders(15).then(res => {
      setData(res.data);
      setLoading(false);
    }).catch(err => {
      console.error(err);
      setLoading(false);
    });
  }, []);

  const handleSort = (key) => {
    let direction = 'desc';
    if (sortConfig.key === key && sortConfig.direction === 'desc') {
      direction = 'asc';
    }
    setSortConfig({ key, direction });
  };

  const sortedData = [...data].sort((a, b) => {
    if (a[sortConfig.key] < b[sortConfig.key]) {
      return sortConfig.direction === 'asc' ? -1 : 1;
    }
    if (a[sortConfig.key] > b[sortConfig.key]) {
      return sortConfig.direction === 'asc' ? 1 : -1;
    }
    return 0;
  });

  const SortIcon = ({ columnKey }) => {
    if (sortConfig.key !== columnKey) return <span style={{ opacity: 0.3, marginLeft: 4 }}>↕</span>;
    return sortConfig.direction === 'asc' ? <ChevronUp size={14} style={{ display: 'inline', marginLeft: 4 }} /> : <ChevronDown size={14} style={{ display: 'inline', marginLeft: 4 }} />;
  };

  if (loading) return <div className="loading-spinner"></div>;

  return (
    <div className="animate-fade-in">
      <div className="flex-between mb-8">
        <div>
          <h1>Worst Offenders</h1>
          <p className="subtitle">Top vehicles ranked by weighted idle waste score</p>
        </div>
      </div>

      <div className="glass-panel">
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th onClick={() => handleSort('vin')} style={{ cursor: 'pointer' }}>Vehicle (VIN) <SortIcon columnKey="vin" /></th>
                <th onClick={() => handleSort('fuel_type')} style={{ cursor: 'pointer' }}>Fuel <SortIcon columnKey="fuel_type" /></th>
                <th onClick={() => handleSort('avg_idle_min')} style={{ cursor: 'pointer' }}>Avg Idle (min/day) <SortIcon columnKey="avg_idle_min" /></th>
                <th onClick={() => handleSort('avg_idle_pct')} style={{ cursor: 'pointer' }}>Idle % <SortIcon columnKey="avg_idle_pct" /></th>
                <th onClick={() => handleSort('total_idle_cost')} style={{ cursor: 'pointer' }}>Total Idle Cost <SortIcon columnKey="total_idle_cost" /></th>
                <th onClick={() => handleSort('weighted_score')} style={{ cursor: 'pointer' }}>Risk Score <SortIcon columnKey="weighted_score" /></th>
              </tr>
            </thead>
            <tbody>
              {sortedData.map((row, idx) => (
                <tr 
                  key={row.vin} 
                  className="table-row-clickable"
                  onClick={() => navigate(`/vehicle/${row.vehicle_id}`, { state: { vin: row.vin } })}
                >
                  <td>
                    <span className={`badge ${idx < 3 ? 'badge-danger' : 'badge-warning'}`}>
                      #{idx + 1}
                    </span>
                  </td>
                  <td style={{ fontWeight: 600 }}>{row.vin}</td>
                  <td style={{ textTransform: 'capitalize' }}>{row.fuel_type}</td>
                  <td>{row.avg_idle_min.toFixed(1)}</td>
                  <td>{row.avg_idle_pct.toFixed(1)}%</td>
                  <td className="text-danger font-bold">{formatINR(row.total_idle_cost)}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {row.weighted_score.toFixed(2)}
                      {row.weighted_score > 2.0 && <AlertCircle size={14} className="text-danger" />}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
