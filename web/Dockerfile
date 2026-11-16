FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_URL=/api
ARG VITE_PAYPAL_STUB=true
ARG VITE_PAYPAL_CLIENT_ID=
ARG VITE_PAYPAL_SDK_URL=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PAYPAL_STUB=$VITE_PAYPAL_STUB
ENV VITE_PAYPAL_CLIENT_ID=$VITE_PAYPAL_CLIENT_ID
ENV VITE_PAYPAL_SDK_URL=$VITE_PAYPAL_SDK_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80