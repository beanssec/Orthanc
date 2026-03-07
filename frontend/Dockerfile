FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
RUN npm run build
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
