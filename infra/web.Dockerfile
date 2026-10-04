# Web dev image: Vite dev server. node_modules live in the image (an anonymous volume at
# run time), the source is bind-mounted at /app/web. It runs as the worktree owner's uid and
# gid (the Makefile passes HOST_UID and HOST_GID), so nothing it writes into the worktree is
# root's; node_modules is theirs too, for Vite's cache.
FROM node:22-trixie-slim
ARG UID=1000
ARG GID=1000
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund && chown -R "$UID:$GID" /app/web
USER $UID:$GID
ENV HOME=/tmp
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
