#!/usr/bin/env bash
# NAS incident 2026-09-13 / 2026-09-14 (local time) - READ-ONLY evidence collection. v2.
#
#   sudo bash /volume1/docker/nas-incident-20260914/collect_readonly.sh
#
# v2 (2026-09-20): repository-canonical copy of the collector that was staged on the NAS on
# 2026-09-14 and never executed. Adds the post-incident stability window (15.09-20.09): boot
# timeline since the incident, thermal/SMART keyword scan and Docker events for that period,
# and a 90-SUMMARY.txt file. Still strictly read-only.
#
# Reads hardware/SMART/temperature state, boot/shutdown timeline, system and Docker daemon logs,
# `docker inspect` (State/RestartCount only — never Config.Env) and begwork-backend logs for the
# two windows. Writes ONLY into /volume1/docker/nas-incident-20260914/out-<stamp>/.
# No restart, no rebuild, no container start, no SMART self-test, no settings change.
# Backend log windows are redacted against the secret-type production .env values (keys like *SECRET*,
# *PASS*, *TOKEN*, *KEY*, MONGO*, *URI*, or URLs with credentials) inside awk; values are never printed.
set -u
umask 022
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/out-$(date +%Y%m%dT%H%M%S)"
mkdir -p "$OUT" || exit 2
PROD=/volume1/docker/begwork
W1_FROM="2026-09-13 19:00:00"; W1_TO="2026-09-13 20:00:00"   # local time, around 19:33-19:34
W2_FROM="2026-09-14 13:45:00"; W2_TO="2026-09-14 14:45:00"   # local time, around 14:16-14:17

run() { # run NAME command... -> $OUT/NAME.txt (stdout+stderr, capped, never fatal)
  local name="$1"; shift
  { echo "\$ $*"; timeout 120 "$@" 2>&1 | head -n 4000; echo "[exit ${PIPESTATUS[0]}]"; } > "$OUT/$name.txt" 2>&1
}
have() { command -v "$1" >/dev/null 2>&1; }
iso() { date -d "$1" +%Y-%m-%dT%H:%M:%S%z | sed 's/\([0-9][0-9]\)$/:\1/'; }

echo "collecting into $OUT"
# ---------------------------------------------------------------- system / timeline
run 00-date date; echo "TZ=$(cat /etc/TZ 2>/dev/null) $(readlink /etc/localtime 2>/dev/null)" >> "$OUT/00-date.txt"
run 01-uptime uptime
run 01-uptime-since uptime -s
run 02-version cat /etc.defaults/VERSION
run 03-boots journalctl --list-boots --no-pager
run 04-last last -x -F
run 05-meminfo head -n 20 /proc/meminfo
run 05-free free -m
if have journalctl; then
  run 10-journal-prev-boot-tail journalctl -b -1 -n 400 --no-pager
  run 11-journal-current-boot-head journalctl -b 0 -n 300 --no-pager --reverse
  run 12-journal-w1 journalctl --since "$W1_FROM" --until "$W1_TO" --no-pager
  run 13-journal-w2 journalctl --since "$W2_FROM" --until "$W2_TO" --no-pager
  run 14-journal-keywords sh -c "journalctl --since '2026-09-12 00:00:00' --no-pager | grep -iE 'therm|temperat|overheat|over-heat|fan|shutdown|power.?off|reboot|halt|oom|out of memory|killed process|smart|I/O error|critical|scemd' | tail -n 1500"
  run 15-journal-kernel-prev-boot sh -c "journalctl -k -b -1 --no-pager | grep -iE 'oom|killed process|therm|temperat|ata[0-9]|sata|I/O error|md[0-9]|btrfs|power|shutdown|halt' | tail -n 500"
fi
run 16-dmesg-keywords sh -c "dmesg -T 2>/dev/null | grep -iE 'oom|killed process|therm|temperat|ata[0-9]|sata|I/O error|btrfs|md[0-9]' | tail -n 400"
run 17-varlog-list ls -la --time-style=full-iso /var/log /var/log/synolog
for f in /var/log/messages* /var/log/scemd.log* /var/log/kern.log* /var/log/disk.log* /var/log/hwmon.log* /var/log/synoscgi.log*; do
  [ -f "$f" ] || continue
  n="20-log-$(basename "$f" | tr -c 'A-Za-z0-9._-' '_')"
  case "$f" in
    *.xz) run "$n" sh -c "xz -dc '$f' | grep -iE 'therm|temperat|overheat|fan|shutdown|power.?off|reboot|halt|oom|out of memory|killed process|smart|I/O error|critical|docker' | grep -E '2026-09-(1[2-9]|20)|Sep (1[2-9]|20)' | tail -n 800" ;;
    *.gz) run "$n" sh -c "zcat '$f' | grep -iE 'therm|temperat|overheat|fan|shutdown|power.?off|reboot|halt|oom|out of memory|killed process|smart|I/O error|critical|docker' | grep -E '2026-09-(1[2-9]|20)|Sep (1[2-9]|20)' | tail -n 800" ;;
    *) run "$n" sh -c "grep -iE 'therm|temperat|overheat|fan|shutdown|power.?off|reboot|halt|oom|out of memory|killed process|smart|I/O error|critical|docker' '$f' | grep -E '2026-09-(1[2-9]|20)|Sep (1[2-9]|20)' | tail -n 800" ;;
  esac
done
if have sqlite3; then
  for db in /var/log/synolog/synosys.db /var/log/synolog/synoconn.db; do
    [ -f "$db" ] || continue
    n="21-synolog-$(basename "$db" .db)"
    run "$n-schema" sqlite3 "$db" .schema
    run "$n-recent" sqlite3 -header -separator ' | ' "$db" "select * from logs order by rowid desc limit 600"
  done
else
  echo "sqlite3 not available" > "$OUT/21-synolog-unavailable.txt"
fi

# ---------------------------------------------------------------- hardware: disks, SMART, temps, fans
run 30-disks-dev sh -c "ls -la /dev/sata* /dev/sd? /dev/nvme* 2>/dev/null"
have synodisk && run 31-synodisk-enum synodisk --enum -t internal
for d in /dev/sata1 /dev/sata2 /dev/sata3 /dev/sata4 /dev/sda /dev/sdb /dev/sdc /dev/sdd; do
  [ -b "$d" ] || continue
  b="$(basename "$d")"
  have synodisk && run "32-temp-$b" synodisk --read_temp "$d"
  have smartctl && run "33-smart-$b" smartctl -d sat -i -H -A -l error -l selftest "$d"
done
for d in /dev/nvme0 /dev/nvme1; do
  [ -e "$d" ] || continue
  have smartctl && run "34-smart-$(basename "$d")" smartctl -i -H -A -l error "$d"
done
run 35-run-synostorage sh -c "for f in /run/synostorage/disks/*/*; do [ -f \"\$f\" ] && [ \$(stat -c %s \"\$f\") -lt 512 ] && printf '%s = %s\n' \"\$f\" \"\$(tr -d '\n' < \"\$f\")\"; done"
run 36-hwmon sh -c "for f in /sys/class/hwmon/hwmon*/name /sys/class/hwmon/hwmon*/temp*_input /sys/class/hwmon/hwmon*/temp*_label /sys/class/hwmon/hwmon*/fan*_input /sys/class/thermal/thermal_zone*/type /sys/class/thermal/thermal_zone*/temp; do [ -f \"\$f\" ] && printf '%s = %s\n' \"\$f\" \"\$(cat \"\$f\")\"; done"
if [ -x /usr/syno/bin/synowebapi ]; then
  run 37-api-system-info /usr/syno/bin/synowebapi --exec api=SYNO.Core.System method=info version=3
  run 38-api-storage /usr/syno/bin/synowebapi --exec api=SYNO.Storage.CGI.Storage method=load_info version=1
  run 39-api-fan /usr/syno/bin/synowebapi --exec api=SYNO.Core.Hardware.FanSpeed method=get version=1
  run 39-api-utilization /usr/syno/bin/synowebapi --exec api=SYNO.Core.System.Utilization method=get version=1
fi
run 40-mdstat cat /proc/mdstat
run 40-volumes sh -c "df -h /volume1 /volume2 2>/dev/null; mount | grep -E '/volume[0-9]'"
# is the photo move (/home/Photos_KPO -> /Photo) or another bulk copy still running? (process list + 10 s I/O sample only;
# no directory walk of the photo folders)
run 41-processes sh -c "ps -eo pid,ppid,etime,pcpu,pmem,stat,args --sort=-pcpu | head -n 60"
run 42-copy-processes sh -c "ps -eo pid,etime,pcpu,stat,args | grep -iE 'rsync|[ /]cp |[ /]mv |synofile|filestation|copymove|photo|kpo' | grep -v grep"
run 43-diskstats-10s sh -c "grep -E ' (sata[0-9]|sd[a-z]|nvme[0-9]n[0-9]|md[0-9]) ' /proc/diskstats; sleep 10; echo '--- +10s'; grep -E ' (sata[0-9]|sd[a-z]|nvme[0-9]n[0-9]|md[0-9]) ' /proc/diskstats"
run 44-loadavg cat /proc/loadavg

# ---------------------------------------------------------------- docker (read-only)
run 50-docker-ps docker ps -a --format '{{.Names}} | {{.ID}} | {{.Image}} | {{.Status}} | {{.CreatedAt}}'
for c in begwork-backend begwork-frontend kpo-photo-cleaner; do
  run "51-inspect-$c" docker inspect -f 'name={{.Name}} created={{.Created}} image={{.Image}} restart_count={{.RestartCount}} restart_policy={{.HostConfig.RestartPolicy.Name}} status={{.State.Status}} running={{.State.Running}} restarting={{.State.Restarting}} oom_killed={{.State.OOMKilled}} dead={{.State.Dead}} exit_code={{.State.ExitCode}} error={{.State.Error}} pid={{.State.Pid}} started_at={{.State.StartedAt}} finished_at={{.State.FinishedAt}} memory_limit={{.HostConfig.Memory}} log_path={{.LogPath}}' "$c"
done
run 52-docker-info sh -c "docker info 2>&1 | grep -iE 'server version|storage driver|logging driver|cgroup|kernel|total memory|cpus|docker root|containers|running|stopped|live restore'"
run 53-docker-stats docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} {{.MemPerc}}'
run 54-docker-events sh -c "docker events --since '$(iso "2026-09-13 00:00:00")' --until '$(date +%Y-%m-%dT%H:%M:%S%z | sed 's/\([0-9][0-9]\)$/:\1/')' --filter type=container --filter type=daemon 2>&1 | tail -n 500"
if have systemctl; then
  run 55-docker-units sh -c "systemctl list-units --all --no-pager | grep -iE 'docker|containerd|container'"
  for u in pkg-ContainerManager-dockerd pkg-ContainerManager-termd pkg-Docker-dockerd; do
    run "56-journal-$u-w1" journalctl -u "$u" --since "$W1_FROM" --until "$W1_TO" --no-pager
    run "57-journal-$u-w2" journalctl -u "$u" --since "$W2_FROM" --until "$W2_TO" --no-pager
    run "58-journal-$u-prev-boot-tail" journalctl -u "$u" -b -1 -n 200 --no-pager
  done
fi
run 59-docker-logfiles sh -c "ls -la --time-style=full-iso /var/log/*docker* /var/packages/ContainerManager/var/*.log /var/packages/Docker/var/*.log 2>/dev/null; for f in /var/log/docker.log /var/packages/ContainerManager/var/docker.log; do [ -f \"\$f\" ] && grep -E '2026-09-(1[3-9]|20)' \"\$f\" | tail -n 600; done"

# backend logs in the two windows (+ restart-related lines since 12.09), redacted against .env values
redact() {
  if [ -r "$PROD/.env" ]; then
    awk 'NR==FNR { i = index($0, "="); if (i > 0) { v = substr($0, i + 1); sub(/^[ \t]+/, "", v); sub(/[ \t\r]+$/, "", v);
                     if (v ~ /^".*"$/ || v ~ /^'\''.*'\''$/) v = substr(v, 2, length(v) - 2); k = substr($0, 1, i - 1); if (length(v) >= 6 && (k ~ /SECRET|PASS|TOKEN|KEY|MONGO|URI|CREDENTIAL|PRIVATE|AUTH/ || v ~ /:\/\/[^\/]*:[^\/]*@/)) vals[++n] = v } next }
         { for (k = 1; k <= n; k++) while ((p = index($0, vals[k])) > 0) $0 = substr($0, 1, p - 1) "***REDACTED***" substr($0, p + length(vals[k])); print }' \
        "$PROD/.env" -
  else
    echo "(.env unreadable: output withheld)"; cat > /dev/null
  fi
}
for c in begwork-backend begwork-frontend; do  # kpo-photo-cleaner logs deliberately not collected (private photo paths)
  { docker logs --timestamps --since "$(iso "$W1_FROM")" --until "$(iso "$W1_TO")" "$c" 2>&1 | tail -n 3000; } | redact > "$OUT/60-logs-$c-w1.txt"
  { docker logs --timestamps --since "$(iso "$W2_FROM")" --until "$(iso "$W2_TO")" "$c" 2>&1 | tail -n 3000; } | redact > "$OUT/61-logs-$c-w2.txt"
done
{ docker logs --timestamps --since "$(iso "2026-09-12 00:00:00")" begwork-backend 2>&1 \
    | grep -iE 'Traceback|Error|Exception|Started server process|Application startup|Shutting down|Finished server process|Waiting for application|Uvicorn running|killed|signal|MemoryError|ServerSelectionTimeout' | tail -n 1500; } | redact > "$OUT/62-logs-backend-lifecycle.txt"

# ---------------------------------------------------------------- post-incident stability (15.09 - today)
POST_FROM="2026-09-15 00:00:00"
if have journalctl; then
  run 80-boots-since-incident sh -c "journalctl --list-boots --no-pager | tail -n 20"
  run 81-journal-post-thermal sh -c "journalctl --since '$POST_FROM' --no-pager | grep -iE 'therm|temperat|overheat|fan|shutdown|power.?off|reboot|halt|oom|killed process|smart|I/O error|critical' | tail -n 800"
fi
run 82-docker-events-post sh -c "docker events --since '$(iso "2026-09-15 00:00:00")' --until '$(iso "$(date "+%Y-%m-%d %H:%M:%S")")' --filter type=container --filter type=daemon 2>&1 | tail -n 500"
run 83-container-uptimes docker ps --format '{{.Names}} | {{.Status}} | {{.RunningFor}}'

# ---------------------------------------------------------------- app / backup side effects
run 70-backups ls -la --time-style=full-iso "$PROD/backups"
run 71-crontab cat /etc/crontab
run 72-health sh -c "curl -s -o /dev/null -m 10 -w 'health %{http_code}\n' http://127.0.0.1:8080/api/health"

# secret guard: no collected file may contain an .env value (fail closed: if the check itself
# fails, every log-derived file is emptied)
if [ -r "$PROD/.env" ]; then
  if leaks="$(awk 'NR==FNR { i = index($0, "="); if (i > 0) { v = substr($0, i + 1); sub(/^[ \t]+/, "", v); sub(/[ \t\r]+$/, "", v);
                     if (v ~ /^".*"$/ || v ~ /^'\''.*'\''$/) v = substr(v, 2, length(v) - 2); k = substr($0, 1, i - 1); if (length(v) >= 6 && (k ~ /SECRET|PASS|TOKEN|KEY|MONGO|URI|CREDENTIAL|PRIVATE|AUTH/ || v ~ /:\/\/[^\/]*:[^\/]*@/)) vals[++n] = v } next }
                   { for (k = 1; k <= n; k++) if (index($0, vals[k]) > 0) print FILENAME }' "$PROD/.env" "$OUT"/*.txt)"; then
    leaks="$(printf '%s\n' "$leaks" | sort -u | sed '/^$/d')"
    if [ -n "$leaks" ]; then
      for f in $leaks; do : > "$f"; echo "emptied (contained an .env value): $(basename "$f")" >> "$OUT/99-secret-guard.txt"; done
    else
      echo "secret guard: no .env value found in the collected files" > "$OUT/99-secret-guard.txt"
    fi
  else
    for f in "$OUT"/1*.txt "$OUT"/2*.txt "$OUT"/5*.txt "$OUT"/6*.txt; do : > "$f"; done
    echo "secret guard FAILED to run: log-derived files emptied" > "$OUT/99-secret-guard.txt"
  fi
else
  for f in "$OUT"/6*.txt; do : > "$f"; done
  echo "secret guard: .env unreadable, container logs emptied" > "$OUT/99-secret-guard.txt"
fi
{
  echo "collector v2 finished: $(date +%Y-%m-%dT%H:%M:%S%z)"
  echo "uptime: $(uptime 2>/dev/null)"
  echo "booted: $(uptime -s 2>/dev/null)"
  echo "--- container restart counts ---"
  for c in begwork-backend begwork-frontend kpo-photo-cleaner; do
    printf '%s: %s
' "$c" "$(docker inspect -f '{{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}} started={{.State.StartedAt}}' "$c" 2>&1)"
  done
  echo "--- nightly backups present ---"
  ls "$PROD/backups" 2>/dev/null | grep 'archive.gz' | tail -n 16
} > "$OUT/90-SUMMARY.txt" 2>&1

echo "done: $OUT"
ls "$OUT" | wc -l
