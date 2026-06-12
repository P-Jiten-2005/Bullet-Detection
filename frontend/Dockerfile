FROM node:18-alpine AS builder
WORKDIR /app

# Copy package config and lock
COPY package*.json ./
RUN npm install --frozen-lockfile

# Copy codebase
COPY . .

# Build Next.js application
RUN npm run build

# Runner Stage
FROM node:18-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Copy built outputs and runtime dependencies
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public

EXPOSE 3000

# Start production server
CMD ["npm", "start"]
