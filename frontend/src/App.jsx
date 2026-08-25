/**
 * Application shell.
 *
 * No top navbar: the dashboard sidebar is the navigation, and the officer
 * console is reached from its footer link. Routes are flat and few.
 */

import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, RequireOfficer } from './auth/AuthContext.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Login from './pages/Login.jsx';
import OfficerConsole from './pages/OfficerConsole.jsx';

function NotFound() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <p className="text-md font-semibold text-ink">Page not found</p>
      <NavLink to="/dashboard" className="btn">
        Back to dashboard
      </NavLink>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <div className="h-full bg-white text-ink">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/officer/login" element={<Login />} />
          <Route
            path="/officer"
            element={
              <RequireOfficer>
                <OfficerConsole />
              </RequireOfficer>
            }
          />
          {/* The console used to live at /officer/console; keep that working. */}
          <Route
            path="/officer/console"
            element={<Navigate to="/officer" replace />}
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </AuthProvider>
  );
}
