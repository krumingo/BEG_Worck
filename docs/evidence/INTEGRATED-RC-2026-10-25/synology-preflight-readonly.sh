#!/usr/bin/env bash
# Read-only operational evidence. No credentials, restarts, writes or image pulls.
set -eu
root=/volume1/docker/begwork
printf 'UTC: '; date -u '+%Y-%m-%dT%H:%M:%SZ'
printf '\nDeployment source marker:\n'
cat "$root/DEPLOYED_COMMIT"
printf '\nCurrent runtime identities:\n'
for name in begwork-backend begwork-frontend; do
  docker inspect --format 'name={{.Name}} image_id={{.Image}} configured_image={{.Config.Image}} state={{.State.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}}' "$name"
done
printf '\nVersioned layout checksums (no .env content):\n'
for name in docker-compose.yml Dockerfile.backend Dockerfile.frontend nginx.conf; do
  if [ -f "$root/$name" ]; then sha256sum "$root/$name"; else printf 'MISSING %s\n' "$name"; fi
done
printf '\nSpace:\n'
df -h "$root"
printf '\nAvailable temperature sensor readings (millidegrees Celsius):\n'
found=0
for sensor in /sys/class/hwmon/hwmon*/temp*_input; do
  [ -r "$sensor" ] || continue
  found=1
  printf '%s=' "$sensor"; cat "$sensor"
done
[ "$found" -eq 1 ] || printf 'UNKNOWN: no readable hwmon temperature sensors; thermal gate NOT cleared\n'
printf '\nNamed backup identity:\n'
backup="$root/backups/begwork_atlas_2026-10-25_0310.archive.gz"
if [ -f "$backup" ]; then
  sha256sum "$backup"
  gzip -t "$backup"
  printf 'gzip integrity PASS; restore is NOT proved by this check\n'
else
  printf 'MISSING named backup\n'
  exit 2
fi
printf '\nPreflight collected. Restore, image export/load and rollback remain separate gates.\n'
