EXPOSEn node:20-alpine
WORKDIR /app
COPY package.json .
RUN npm install --omit=dev
COPY server.js .
COPY index.htmlCOPPOSEOSE 4000
CMD ["node", "server.js"]
