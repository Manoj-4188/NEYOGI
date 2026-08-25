/** Officer sign-in. The dashboard is public; only this console is gated. */

import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext.jsx';

export default function Login() {
  const { login, principal, error, checking } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!checking && principal) {
    return <Navigate to={location.state?.from || '/officer'} replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    const ok = await login(username, password);
    setSubmitting(false);
    if (ok) navigate(location.state?.from || '/officer', { replace: true });
  }

  return (
    <div className="flex h-full items-center justify-center">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-[320px] border border-line p-6 shadow-card"
        style={{ borderRadius: 4 }}
      >
        <p className="text-md font-bold text-ink">NEYOGI</p>
        <p className="mt-0.5 text-xs text-muted">Officer console</p>

        <div className="mt-5 space-y-3">
          <div>
            <label className="text-xs text-muted" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className="field mt-1"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs text-muted" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="field mt-1"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
        </div>

        {error ? <p className="mt-4 text-sm text-high">{error}</p> : null}

        <button type="submit" className="btn mt-5 w-full" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
