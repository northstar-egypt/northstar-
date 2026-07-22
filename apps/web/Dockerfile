# NorthStar web image for local development.
# Runs the Next.js dev server. A multi-stage production build comes later (TODO).
FROM node:20-slim

WORKDIR /app

# Install dependencies first for layer caching. In local dev docker-compose also mounts the
# source over this, but baking deps in keeps a cold `docker compose up` working on its own.
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
