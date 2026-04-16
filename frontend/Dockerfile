# FXLab Frontend — Multi-stage Dockerfile
#
# Stage 1 (builder): npm ci + vite build
# Stage 2 (runtime): nginx serves the static dist/
#
# The nginx config proxies /api/* to the API container so the frontend
# and API share the same origin from the browser's perspective.

# ---------------------------------------------------------------------------
# Stage 1: build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Copy lock files first for better layer caching.
# package-lock.json* glob allows the COPY to succeed even if the lockfile
# is missing. npm ci requires a lockfile; fall back to npm install if absent.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --prefer-offline; else npm install --prefer-offline; fi

# Copy source and build.
# VITE_API_BASE_URL is baked into the JS bundle at build time by Vite.
# Default: /api (relative — works behind the nginx proxy on any host).
# Override via docker-compose build args or --build-arg for custom setups.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: nginx runtime
# ---------------------------------------------------------------------------
FROM nginx:1.25-alpine AS runtime

RUN apk add --no-cache curl

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom nginx config: serve SPA + proxy /api to API container
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -sf http://localhost:3000 || exit 1

CMD ["nginx", "-g", "daemon off;"]
