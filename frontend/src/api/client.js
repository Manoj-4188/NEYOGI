/**
 * Thin fetch wrapper for the NEYOGI API.
 *
 * Two rules worth keeping in mind when using this module:
 *
 * 1. Status badges come from the server. The UI renders `payload.status`; it
 *    never decides on its own whether data is live or cached.
 * 2. A 503 is a normal, expected outcome (PostGIS or a feed is down) and is
 *    surfaced as an ApiError the caller renders as a banner — not swallowed.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const TOKEN_KEY = 'neyogi.officer.token';

export class ApiError extends Error {
  constructor(message, { status, payload } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }

  /** True when the failure is a dependency outage rather than a bad request. */
  get isOutage() {
    return this.status === 503 || this.status === 0;
  }
}

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing or blocked storage — the console just needs a re-login.
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* non-fatal */
  }
}

function buildUrl(path, params) {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

async function request(path, { params, method = 'GET', body, auth = false } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError('Could not reach the NEYOGI API.', { status: 0, payload: { cause: String(cause) } });
  }

  if (response.status === 204) return null;

  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth) setToken(null);
    const detail = payload?.detail || `Request failed with HTTP ${response.status}`;
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), {
      status: response.status,
      payload,
    });
  }

  return payload;
}

/* -------------------------------------------------------------------------
 * Public endpoints
 * ---------------------------------------------------------------------- */

export const api = {
  health: () => request('/health'),

  districts: () => request('/api/v1/map/districts'),

  crops: ({ district, onDate, includeUnverified = true, includeTile = true, limit }) =>
    request('/api/v1/map/crops', {
      params: {
        district,
        on_date: onDate,
        include_unverified: includeUnverified,
        include_tile: includeTile,
        limit,
      },
    }),

  supplyForecast: ({ district, windowDays }) =>
    request('/api/v1/forecast/supply', {
      params: { district, window_days: windowDays },
    }),

  mandiPrices: ({ district, crop, includeAverage = true }) =>
    request('/api/v1/prices/mandi', {
      params: { district, crop, include_average: includeAverage },
    }),

  parcelSeries: ({ parcelId, index, since }) =>
    request(`/api/v1/parcel/${parcelId}/ndvi`, { params: { index, since } }),

  coldStorage: ({ district }) =>
    request('/api/v1/infrastructure/cold-storage', { params: { district } }),

  /* -----------------------------------------------------------------------
   * Officer endpoints (bearer token required)
   * -------------------------------------------------------------------- */

  login: ({ username, password }) =>
    request('/api/v1/auth/login', { method: 'POST', body: { username, password } }),

  me: () => request('/api/v1/auth/me', { auth: true }),

  telemetry: () => request('/api/v1/officer/telemetry', { auth: true }),

  model: () => request('/api/v1/officer/model', { auth: true }),

  runs: ({ stage, limit = 50 } = {}) =>
    request('/api/v1/officer/runs', { params: { stage, limit }, auth: true }),

  reviewParcels: ({ district, verified, limit = 100 }) =>
    request('/api/v1/officer/parcels', {
      params: { district, verified, limit },
      auth: true,
    }),

  setVerification: ({ parcelId, verified, cropLabel }) =>
    request(`/api/v1/officer/parcels/${parcelId}/verify`, {
      method: 'POST',
      auth: true,
      body: { verified, crop_label: cropLabel ?? null },
    }),
};

export default api;
