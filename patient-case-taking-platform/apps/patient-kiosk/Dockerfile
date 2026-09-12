FROM node:22-alpine AS base
WORKDIR /workspace/apps/patient-kiosk

FROM base AS deps
COPY apps/patient-kiosk/package.json ./
COPY apps/patient-kiosk/package-lock.json ./
RUN npm ci

FROM base AS builder
COPY --from=deps /workspace/apps/patient-kiosk/node_modules ./node_modules
COPY apps/patient-kiosk ./
COPY packages/ui-system /workspace/packages/ui-system
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /workspace/apps/patient-kiosk/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/apps/patient-kiosk/.next/static ./apps/patient-kiosk/.next/static

USER node
EXPOSE 3000
CMD ["node", "apps/patient-kiosk/server.js"]
