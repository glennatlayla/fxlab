# FXLab Nginx Edge Proxy
#
# Extends the stock nginx:1.25-alpine with curl for healthchecks.
# The fxlab.conf is mounted via docker-compose volume, not baked in,
# so config changes don't require an image rebuild.

FROM nginx:1.25-alpine

RUN apk add --no-cache curl
