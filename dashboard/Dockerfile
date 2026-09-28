# Build stage
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Accept VITE_API_BASE as a build-time arg so the API URL is baked into
# the static bundle. Falls back to /api (nginx reverse proxy) if unset.
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build

# Serve stage
FROM nginx:alpine

# Custom nginx config with /api reverse proxy to api container
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets to Nginx
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
