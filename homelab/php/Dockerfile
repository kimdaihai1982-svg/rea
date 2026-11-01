FROM trafex/php-nginx:3.8.0
USER root
# This base uses PHP 8.4 and /run/php-fpm.sock (not PHP 8.3/TCP 9000).
RUN apk add --no-cache php84-pdo_mysql \
    && test "$PHP_INI_DIR" = /etc/php84 \
    && test -d "$PHP_INI_DIR/php-fpm.d" \
    && printf '\n[www]\nclear_env = yes\nenv[DB_USERNAME] = $DB_USERNAME\nenv[DB_PASSWORD] = $DB_PASSWORD\n' > "$PHP_INI_DIR/php-fpm.d/zz-app-env.conf"
USER nobody
