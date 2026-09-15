# The web container: a static production build served by nginx, which also
# proxies /api and /ws to the api service so the browser sees one origin
# (frontend.md §6.7). Build context is web/.

FROM node:22-alpine AS build
WORKDIR /app

# corepack resolves the exact pnpm named in package.json's `packageManager`
# field, so the image is reproducible and a future pnpm major cannot change how
# the lockfile or pnpm-workspace.yaml are read.
RUN corepack enable

# Dependencies first: this layer is cached until the lockfile changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
# VITE_USE_MOCKS is deliberately unset: no mock code is reachable from this build.
RUN pnpm build

FROM nginx:1.27-alpine AS runtime

# nginx:alpine ships a default site; ours replaces it wholesale.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/xpm.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
