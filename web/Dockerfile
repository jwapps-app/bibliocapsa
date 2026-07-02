FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Serve the pdf.js worker as a static asset (avoids bundling its .mjs through webpack).
RUN mkdir -p public && cp node_modules/pdfjs-dist/build/pdf.worker.min.mjs public/pdf.worker.min.mjs
ENV NEXT_TELEMETRY_DISABLED=1
# Version is read from package.json by next.config.js — nothing to pass here.
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
EXPOSE 3000
# Run as the built-in non-root user (the standalone server only reads files).
USER node
CMD ["node", "server.js"]
