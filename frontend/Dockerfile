# Build context is the REPO ROOT (same convention as backend/Dockerfile) so the
# image builds identically locally and on Railway (RAILWAY_DOCKERFILE_PATH).
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM nginx:alpine
# Copied as a template: the stock entrypoint envsubsts ${BACKEND_HOST} into
# /etc/nginx/conf.d/default.conf at startup (backend locally, *.railway.internal on Railway).
ENV BACKEND_HOST=backend
# Docker's embedded DNS; on Railway override with the private-network resolver (fd12::10).
ENV NGINX_RESOLVER=127.0.0.11
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
