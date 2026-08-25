/**
 * Officer session state.
 *
 * The token lives in localStorage so a console reload does not force a
 * re-login. Role gating is enforced by the API — this context only decides
 * what to render, never what the user is allowed to do.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import api, { getToken, setToken } from '../api/client.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [principal, setPrincipal] = useState(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState(null);

  // Validate any stored token once on mount, so an expired session shows the
  // login screen rather than a console full of 401s.
  useEffect(() => {
    let cancelled = false;
    async function verify() {
      if (!getToken()) {
        if (!cancelled) setChecking(false);
        return;
      }
      try {
        const me = await api.me();
        if (!cancelled) setPrincipal(me);
      } catch {
        setToken(null);
        if (!cancelled) setPrincipal(null);
      } finally {
        if (!cancelled) setChecking(false);
      }
    }
    verify();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username, password) => {
    setError(null);
    try {
      const result = await api.login({ username, password });
      setToken(result.access_token);
      setPrincipal({ username: result.username, role: result.role });
      return true;
    } catch (err) {
      setError(err.message || 'Sign-in failed.');
      return false;
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setPrincipal(null);
  }, []);

  const value = useMemo(
    () => ({ principal, checking, error, login, logout, isOfficer: Boolean(principal) }),
    [principal, checking, error, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider');
  return context;
}

/** Route wrapper that redirects to the login page when unauthenticated. */
export function RequireOfficer({ children }) {
  const { principal, checking } = useAuth();
  const location = useLocation();

  if (checking) {
    return (
      <div className="flex h-full items-center justify-center p-12 text-base text-muted">
        Checking your session…
      </div>
    );
  }
  if (!principal) {
    return <Navigate to="/officer/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}
