# WebUI Docker Container
# Serves the debug/chat interface via nginx

FROM nginx:alpine

# Copy static files
COPY index.html /usr/share/nginx/html/
COPY static/ /usr/share/nginx/html/static/

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
