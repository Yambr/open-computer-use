FROM docker:27-cli

RUN apk add --no-cache bash coreutils findutils

COPY cleanup.sh /usr/local/bin/cleanup.sh
COPY cleanup-quick.sh /usr/local/bin/cleanup-quick.sh
RUN chmod +x /usr/local/bin/cleanup.sh /usr/local/bin/cleanup-quick.sh

# Two cron schedules:
# - Quick: every 2 hours — remove stopped containers + dangling images
# - Full:  daily at 3 AM — stop old containers, clean volumes, prune data
RUN echo "0 */2 * * * /usr/local/bin/cleanup-quick.sh >> /var/log/cleanup.log 2>&1" > /etc/crontabs/root && \
    echo "0 3 * * * /usr/local/bin/cleanup.sh >> /var/log/cleanup.log 2>&1" >> /etc/crontabs/root

CMD ["crond", "-f", "-l", "2"]
