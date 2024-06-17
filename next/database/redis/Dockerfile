FROM redis

RUN apt-get update && apt-get install -y cron

# Copy the startup script
COPY startup.sh /usr/local/bin/startup.sh
# Ensure the startup script is executable
RUN chmod +x /usr/local/bin/startup.sh

# Add the cleanup script and make it executable
COPY cleanup_idle_redis_connections.sh /usr/local/bin/cleanup_idle_redis_connections.sh
RUN chmod +x /usr/local/bin/cleanup_idle_redis_connections.sh

# Create a cron job file
RUN echo "*/5 * * * * /usr/local/bin/cleanup_idle_redis_connections.sh >> /var/log/cleanup_idle_redis_connections.log 2>&1" > /etc/cron.d/simple-cron

 # Set permissions on the cron job
RUN chmod 0644 /etc/cron.d/simple-cron

# Apply the cron job
RUN crontab /etc/cron.d/simple-cron

# Create log files
RUN touch /var/log/cron.log /var/log/cleanup_idle_redis_connections.log

# Set the container's entrypoint to the startup script
CMD ["/usr/local/bin/startup.sh"]

