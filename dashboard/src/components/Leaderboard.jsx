import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getTopOffenders } from '../api';
import { AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { formatINR } from '../formatters';

export default function Leaderboard() {
  const [data, setData] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [sortConfig, setSortConfig] = useState({ key: 'weighted_score', direction: 'desc' });
  const navigate = useNavigate();

  useEffect(() => {
    getTopOffenders(25).then(res => {
      setData(res.data);
      setTotalCount(res.total_count);
    }).catch(err => {
      console.error(err);
      setError(err.message || 'Unable to load fleet offenders.');
    }).finally(() => setLoading(false));
  }, []);

  const loadMore = async () => {
    setLoadingMore(true);
    setError('');
    try {
      const result = await getTopOffenders(25, undefined, undefined, data.length);
      setData(current => [...current, ...result.data]);
      setTotalCount(result.total_count);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Unable to load more fleet offenders.');
    } finally {
      setLoadingMore(false);
    }
  };

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
          <p className="subtitle">Showing {data.length} of {totalCount} vehicles ranked by weighted idle waste score over the latest week</p>
        </div>
      </div>

      {error && <p role="alert" className="text-danger">{error}</p>}

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
        {data.length < totalCount && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                background: 'var(--accent)',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '10px 20px',
                cursor: loadingMore ? 'wait' : 'pointer',
              }}
            >
              {loadingMore ? 'Loading…' : `Load more (${totalCount - data.length} remaining)`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
