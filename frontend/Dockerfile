# ==============================================================================
# Frontend Dockerfile — multi-stage build
# Stages: base -> development | build -> production
# Build a specific stage with: docker build --target development ./frontend
# ==============================================================================

# ---------- Stage: base ----------
FROM node:20-alpine AS base

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# ---------- Stage: development ----------
# Runs the Vite dev server directly with hot module reload, against a
# bind-mounted source tree (see docker-compose.override.yml). Never used
# in production — Vite's dev server is not a production HTTP server.
FROM base AS development

EXPOSE 5173

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --spider -q http://127.0.0.1:5173/ || exit 1

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------- Stage: build ----------
# Produces the static production bundle. Kept separate from the
# "production" stage so the final image never contains node_modules,
# source TypeScript, or the Node runtime itself.
FROM base AS build

RUN npm run build

# ---------- Stage: production ----------
# Serves the static bundle from stage "build" via nginx. This is the
# per-container static file server; the separate reverse-proxy nginx
# (infra/docker/nginx/nginx.conf) sits in front of this container and
# routes browser traffic to it alongside the API.
FROM nginx:1.27-alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --spider -q http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
