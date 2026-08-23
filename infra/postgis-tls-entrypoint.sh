#!/bin/sh
set -eu
install -d -o postgres -g postgres -m 700 /var/lib/postgresql/tls
install -o postgres -g postgres -m 600 /run/secrets/postgres-server-key /var/lib/postgresql/tls/server-key.pem
install -o postgres -g postgres -m 644 /run/secrets/postgres-server-cert /var/lib/postgresql/tls/server-cert.pem
install -o postgres -g postgres -m 644 /run/secrets/tls-ca /var/lib/postgresql/tls/ca-cert.pem
exec /usr/local/bin/docker-entrypoint.sh postgres \
  -c ssl=on \
  -c ssl_min_protocol_version=TLSv1.3 \
  -c ssl_cert_file=/var/lib/postgresql/tls/server-cert.pem \
  -c ssl_key_file=/var/lib/postgresql/tls/server-key.pem \
  -c ssl_ca_file=/var/lib/postgresql/tls/ca-cert.pem \
  -c hba_file=/etc/postgresql/sentinel-pg_hba.conf \
  -c ident_file=/etc/postgresql/sentinel-pg_ident.conf
