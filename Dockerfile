# Stage 1: Build Node.js application
FROM node:18-slim as builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies (using npm install instead of npm ci)
RUN if [ -f package-lock.json ]; then \
      npm ci; \
    else \
      npm install; \
    fi

# Copy application code
COPY . .

# Stage 2: Setup Nginx with Node.js
FROM docker.io/nginx:stable-alpine

# Install Node.js in Nginx image
RUN apk add --update nodejs npm

# Copy Nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Create app directory
WORKDIR /app

# Copy Node.js application from builder
COPY --from=builder /app .

# Expose port
EXPOSE 80

# Create a start script
RUN echo '#!/bin/sh' > /start.sh && \
    echo 'nginx' >> /start.sh && \
    echo 'cd /app && npm start' >> /start.sh && \
    chmod +x /start.sh

# Start both Nginx and Node.js
CMD ["/start.sh"] 