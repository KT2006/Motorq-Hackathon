import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { Activity, Car, LayoutDashboard, Sparkles, LogOut } from 'lucide-react';
import Overview from './components/Overview';
import Leaderboard from './components/Leaderboard';
import VehicleDetail from './components/VehicleDetail';
import AIAssistant from './components/AIAssistant';
import Login from './components/Login';
import { getToken, clearToken } from './api';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken());

  // Listen for 401 events from the fetch wrapper (token expired mid-session)
  useEffect(() => {
    const handler = () => setIsAuthenticated(false);
    window.addEventListener('motorq:unauthorized', handler);
    return () => window.removeEventListener('motorq:unauthorized', handler);
  }, []);

  const handleLogout = () => {
    clearToken();
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <Login onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <Router>
      <div className="app-container">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-logo">
            <Car size={28} />
            Motorq Fleet
          </div>

          <nav className="nav-links">
            <NavLink
              to="/overview"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <LayoutDashboard size={20} />
              Fleet Overview
            </NavLink>

            <NavLink
              to="/leaderboard"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Activity size={20} />
              Worst Offenders
            </NavLink>

            <NavLink
              to="/ai-assistant"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Sparkles size={20} />
              AI Assistant
            </NavLink>
          </nav>

          <div style={{ marginTop: 'auto', padding: '16px' }}>
            <button
              onClick={handleLogout}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                width: '100%',
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: 'var(--text-secondary)',
                padding: '8px 12px',
                cursor: 'pointer',
                fontSize: '13px',
                marginBottom: '12px',
              }}
            >
              <LogOut size={15} />
              Sign Out
            </button>
            <div style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
              Hackathon Build v1.0
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/leaderboard" element={<Leaderboard />} />
            <Route path="/vehicle/:id" element={<VehicleDetail />} />
            <Route path="/ai-assistant" element={<AIAssistant />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
