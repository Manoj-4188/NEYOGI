/** Officer sign-in. The public dashboard needs no account. */

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
    return <Navigate to={location.state?.from || '/officer/console'} replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    const ok = await login(username, password);
    setSubmitting(false);
    if (ok) navigate(location.state?.from || '/officer/console', { replace: true });
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="panel w-full max-w-sm px-6 py-6">
        <h1 className="text-lg font-bold text-forest">Officer sign-in</h1>
        <p className="mt-1 text-sm text-forest-900/60">
          The console exposes pipeline internals and the ground-truth
          verification toggle.
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <label className="field-label" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className="field"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </div>
          <div>
            <label className="field-label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="field"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
        </div>

        {error ? (
          <p className="mt-4 rounded-lg bg-terracotta-100 px-3 py-2 text-sm text-terracotta-600">
            {error}
          </p>
        ) : null}

        <button type="submit" className="btn-primary mt-5 w-full" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="mt-4 border-t border-parchment-200 pt-3 text-xs text-forest-900/50">
          Accounts are seeded from <code className="font-mono">OFFICER_ACCOUNTS</code>.
          Generate a hash with{' '}
          <code className="font-mono">python -m backend.security hash &lt;password&gt;</code>.
        </p>
      </form>
    </div>
  );
}
