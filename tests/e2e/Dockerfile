# Playwright image ships the browsers preinstalled and version-matched to
# @playwright/test, so the run is reproducible (Standards §17).
FROM mcr.microsoft.com/playwright:v1.48.2-jammy

WORKDIR /e2e
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

CMD ["npx", "playwright", "test"]
