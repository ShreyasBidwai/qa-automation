# syntax=docker/dockerfile:1
# Multi-stage build (Engineering Standards §17): resolve node_modules from the
# committed lockfile in a deps stage, then run the Vite dev server in a minimal
# runtime image as the non-root `node` user shipped with the base image.

# ---- deps ------------------------------------------------------------------
FROM node:20.18.0-bookworm-slim AS deps
WORKDIR /app
# `npm ci` is reproducible and requires package-lock.json (installs dev+prod;
# NODE_ENV is intentionally unset here so devDependencies like Vite are present).
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- runtime ---------------------------------------------------------------
FROM node:20.18.0-bookworm-slim AS runtime
ENV NODE_ENV=development
WORKDIR /app
RUN chown node:node /app
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node . .

USER node
EXPOSE 5173

CMD ["npm", "run", "dev"]

# ---- build (production static bundle) ---------------------------------------
# Compiles the Vite app to /app/dist. Uses the deps node_modules (devDeps present
# for tsc/vite). The API base defaults to the relative "/api/v1", so the built
# bundle is single-origin by construction (no baked-in host).
FROM node:20.18.0-bookworm-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---- web (single-origin: nginx serves the SPA + reverse-proxies /api) -------
FROM nginx:1.27-alpine AS web
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# nginx's own image CMD runs the server in the foreground.
