# WebUI Docker Container
# Serves the debug/chat interface via nginx

FROM nginx:alpine

# Fix permissions for non-root user
RUN mkdir -p /var/cache/nginx/client_temp \
             /var/cache/nginx/proxy_temp \
             /var/cache/nginx/fastcgi_temp \
             /var/cache/nginx/uwsgi_temp \
             /var/cache/nginx/scgi_temp && \
    chown -R 1000:1000 /var/cache/nginx && \
    chown -R 1000:1000 /var/run && \
    chown -R 1000:1000 /var/log/nginx && \
    chown -R 1000:1000 /usr/share/nginx/html && \
    touch /var/run/nginx.pid && \
    chown 1000:1000 /var/run/nginx.pid

# Copy static files
COPY --chown=1000:1000 index.html /usr/share/nginx/html/
COPY --chown=1000:1000 style.css /usr/share/nginx/html/
COPY --chown=1000:1000 static/ /usr/share/nginx/html/static/
COPY --chown=1000:1000 js/ /usr/share/nginx/html/js/

# Copy nginx config
COPY --chown=1000:1000 nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
