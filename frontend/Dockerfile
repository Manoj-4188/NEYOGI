# NEYOGI frontend: Vite build, served by nginx.

FROM node:20-alpine AS build

WORKDIR /app

# Lockfile-first for a cacheable install layer. `npm ci` when a lockfile
# exists, `npm install` on a fresh checkout that has none yet.
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

COPY frontend/ ./

# Baked in at build time: Vite inlines VITE_* variables. Empty by default so
# the bundle uses same-origin /api paths, which nginx proxies to the backend.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
