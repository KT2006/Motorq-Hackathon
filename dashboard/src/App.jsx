import { BrowserRouter as Router, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { Activity, Car, LayoutDashboard, Settings, Sparkles } from 'lucide-react';
import Overview from './components/Overview';
import Leaderboard from './components/Leaderboard';
import VehicleDetail from './components/VehicleDetail';
import AIAssistant from './components/AIAssistant';

export default function App() {
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

          <div style={{ marginTop: 'auto', padding: '16px', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <div className="flex-between" style={{ marginBottom: 12 }}>
              <Settings size={16} />
              Settings
            </div>
            Hackathon Build v1.0
          </div>
        </aside>

        {/* Main Content Area */}
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
