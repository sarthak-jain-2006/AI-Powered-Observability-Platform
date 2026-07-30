FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm config set fetch-timeout 300000 && npm install

COPY . .

ENV DATABASE_URL="postgresql://placeholder:placeholder@localhost:5432/placeholder"
RUN npx prisma generate

EXPOSE 3001

CMD ["npm", "start"]