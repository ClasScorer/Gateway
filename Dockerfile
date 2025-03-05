# Stage 1: Build Node.js application
FROM node:18-slim as builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy application code
COPY . .

# Stage 2: Setup Nginx with Node.js
FROM nginx:stable-alpine

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

# Start Nginx and Node.js application
CMD nginx && npm start 