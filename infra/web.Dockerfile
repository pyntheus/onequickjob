# Web dev image: Vite dev server. node_modules live in the image (an anonymous volume at
# run time), the source is bind-mounted at /app/web.
FROM node:22-trixie-slim
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
