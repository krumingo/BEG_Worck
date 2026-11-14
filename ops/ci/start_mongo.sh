#!/usr/bin/env bash
# CI-01 — start a throwaway single-node MongoDB 7.0 replica set (transactions
# need a replica set) on 127.0.0.1:27019 and wait until it is PRIMARY.
# Test data only; no production data or credentials are ever used.
set -euo pipefail
docker run -d --rm --name ci-mongo -p 127.0.0.1:27019:27017 mongo:7.0 \
  --replSet rs0 --bind_ip_all >/dev/null
for _ in $(seq 1 60); do
  docker exec ci-mongo mongosh --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1 && break
  sleep 1
done
docker exec ci-mongo mongosh --quiet --eval \
  'try { rs.status() } catch (e) { rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]}) }' >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker exec ci-mongo mongosh --quiet --eval 'rs.status().myState' 2>/dev/null)" = "1" ] && exit 0
  sleep 1
done
echo "MongoDB replica set did not become PRIMARY" >&2
exit 1
