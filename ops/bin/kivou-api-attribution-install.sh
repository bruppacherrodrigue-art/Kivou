#!/usr/bin/env bash
# Install only the existing attribution key and version; never source acquisition.
set -euo pipefail
[[ $(id -u) == 0 ]] || { printf 'Root required\n' >&2; exit 1; }
case "${1:-}" in
  staging) source_file=/etc/kivou/staging.env ;;
  production) source_file=/etc/kivou/acquisition-production.env ;;
  *) printf 'Usage: kivou-api-attribution-install.sh staging|production\n' >&2; exit 2 ;;
esac
destination=/etc/kivou/api-attribution.env
temporary=$(mktemp /etc/kivou/.api-attribution.XXXXXX)
trap 'rm -f "$temporary"' EXIT
awk '
  /^[[:space:]]*KIVOU_ATTRIBUTION_HMAC_KEY(_VERSION)?=/ {
    line=$0; sub(/^[[:space:]]*/, "", line)
    name=line; sub(/=.*/, "", name)
    if (++seen[name] != 1) bad=1
    print line
  }
  END {
    if (bad || seen["KIVOU_ATTRIBUTION_HMAC_KEY"] != 1 ||
        seen["KIVOU_ATTRIBUTION_HMAC_KEY_VERSION"] != 1) exit 1
  }
' "$source_file" > "$temporary"
chmod 600 "$temporary"
chown root:root "$temporary"
if [[ -e "$destination" ]]; then
  cp -a --backup=numbered "$destination" "${destination}.previous"
fi
mv "$temporary" "$destination"
install -d -m 755 /etc/systemd/system/kivou-api.service.d
printf '[Service]\nEnvironmentFile=/etc/kivou/api-attribution.env\n' \
  > /etc/systemd/system/kivou-api.service.d/60-attribution.conf
systemctl daemon-reload
printf 'Attribution EnvironmentFile installed: key and version only; restart not performed\n'
