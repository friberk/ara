FROM node:24.14.0-bookworm-slim@sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8
WORKDIR /app
COPY --chown=node:node src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci && sha256sum package-lock.json | cut -d ' ' -f 1 > node_modules/.ara-lock-hash && chown -R node:node /app
COPY --chown=node:node src/frontend/ ./
COPY --chmod=755 docker/frontend-entrypoint.sh /usr/local/bin/ara-frontend-entrypoint
USER node
EXPOSE 5173
ENTRYPOINT ["ara-frontend-entrypoint"]
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
