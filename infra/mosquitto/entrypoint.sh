#!/bin/sh
# Monta o arquivo de senhas a partir dos segredos gerados no bootstrap e sobe o
# broker. As senhas ficam no volume de dados, nunca na imagem nem no Git.
set -eu

PASSWD=/mosquitto/data/passwd
: > "$PASSWD"
for user in simulator gateway healthcheck; do
  mosquitto_passwd -b "$PASSWD" "$user" "$(cat "/run/eyewatcher/$user")"
done
chown mosquitto:mosquitto "$PASSWD"
chmod 0700 "$PASSWD"

exec mosquitto -c /mosquitto/config/mosquitto.conf
