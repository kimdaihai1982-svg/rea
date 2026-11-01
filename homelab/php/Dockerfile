FROM trafex/php-nginx:3.8.0
USER root
RUN apk add --no-cache php83-pdo_mysql php83-mysqli php83-opcache
USER nobody
# Pass only application DB settings through FPM's default cleared environment.
USER root
RUN printf '\n[www]\nenv[DB_USERNAME] = $DB_USERNAME\nenv[DB_PASSWORD] = $DB_PASSWORD\n' > /etc/php83/php-fpm.d/zz-app-env.conf
USER nobody
