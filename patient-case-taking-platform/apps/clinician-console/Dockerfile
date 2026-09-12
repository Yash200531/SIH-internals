FROM node:22-alpine AS base
WORKDIR /workspace/apps/clinician-console

FROM base AS deps
COPY apps/clinician-console/package.json ./
COPY apps/clinician-console/package-lock.json ./
RUN npm ci

FROM base AS builder
ARG NEXT_PUBLIC_AUTH_PROVIDER=demo
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_AUTH_PROVIDER=$NEXT_PUBLIC_AUTH_PROVIDER
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /workspace/apps/clinician-console/node_modules ./node_modules
COPY apps/clinician-console ./
COPY packages/ui-system /workspace/packages/ui-system
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /workspace/apps/clinician-console/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/apps/clinician-console/.next/static ./apps/clinician-console/.next/static

USER node
EXPOSE 3000
CMD ["node", "apps/clinician-console/server.js"]
