import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, RequireOfficer, useAuth } from './auth/AuthContext.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Login from './pages/Login.jsx';
import OfficerConsole from './pages/OfficerConsole.jsx';

function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
          isActive
            ? 'bg-forest-700 text-parchment'
            : 'text-parchment/75 hover:bg-forest-700 hover:text-parchment'
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function Header() {
  const { principal } = useAuth();

  return (
    <header className="sticky top-0 z-[500] border-b border-forest-900/40 bg-forest">
      <div className="mx-auto flex max-w-[100rem] items-center gap-4 px-4 py-3 lg:px-8">
        <div className="flex items-baseline gap-2.5">
          <span className="text-lg font-bold tracking-tight text-parchment">NEYOGI</span>
          <span className="hidden text-xs text-parchment/60 sm:inline">
            Enterprise GIS · Perishable Crop Market Intelligence
          </span>
        </div>
        <nav className="ml-auto flex items-center gap-1.5">
          <NavItem to="/dashboard">Dashboard</NavItem>
          <NavItem to={principal ? '/officer/console' : '/officer/login'}>
            Officer Console
          </NavItem>
        </nav>
      </div>
    </header>
  );
}

function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="text-lg font-semibold text-forest">Page not found</p>
      <NavLink to="/dashboard" className="btn-primary">
        Back to the dashboard
      </NavLink>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <div className="flex min-h-full flex-col bg-parchment">
        <Header />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/officer/login" element={<Login />} />
            <Route
              path="/officer/console"
              element={
                <RequireOfficer>
                  <OfficerConsole />
                </RequireOfficer>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
        <footer className="border-t border-parchment-300 px-4 py-4 text-center text-xs text-forest-900/50 lg:px-8">
          Sentinel-2 L2A via Google Earth Engine · mandi prices via AGMARKNET
          (data.gov.in) · district boundaries via FAO GAUL 2015. Crop classes are
          produced only for districts with field-verified ground truth.
        </footer>
      </div>
    </AuthProvider>
  );
}
