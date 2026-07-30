FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm config set fetch-timeout 300000 && npm install

COPY . .

EXPOSE 3003

CMD ["npm", "start"]