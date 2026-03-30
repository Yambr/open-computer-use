FROM docker:27-cli
RUN apk add --no-cache bash coreutils findutils
COPY cleanup.sh /usr/local/bin/cleanup.sh
RUN chmod +x /usr/local/bin/cleanup.sh
# Run cleanup every hour
RUN echo "0 * * * * /usr/local/bin/cleanup.sh >> /var/log/cleanup.log 2>&1" > /etc/crontabs/root
CMD ["crond", "-f", "-l", "2"]
