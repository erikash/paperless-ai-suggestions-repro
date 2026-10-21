#!/usr/bin/env bash
# Standalone reproduction. Requires: docker compose, curl, python3 (3.9+).
#   ./run.sh          bring the stack up, load the documents, show the result
#   ./run.sh down     remove everything (containers, volumes, saved prompts)
set -euo pipefail
cd "$(dirname "$0")"
URL=http://localhost:8010
MOCK=http://localhost:8011
AUTH=(-u admin:admin)

if [ "${1:-}" = down ]; then docker compose down -v; rm -rf prompts; exit; fi

json() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }

docker compose up -d
echo "Waiting for Paperless..."
until curl -sf "${AUTH[@]}" "$URL/api/" >/dev/null 2>&1; do
  if [ -z "$(docker compose ps -q --status running webserver)" ]; then
    docker compose logs --tail 30 webserver; echo "webserver is not running" >&2; exit 1
  fi
  sleep 3
done

corr_id() {
  curl -sf "${AUTH[@]}" -G "$URL/api/correspondents/" --data-urlencode "name__iexact=$1" |
    json 'd["results"][0]["id"] if d["results"] else ""'
}

if [ "$(curl -sf "${AUTH[@]}" "$URL/api/documents/?page_size=1" | json 'd["count"]')" -lt 25 ]; then
  echo "Creating correspondents (auto-matching disabled)..."
  python3 -c 'import json;print("\n".join(sorted({v for v in json.load(open("docs/manifest.json")).values() if v})))' |
  while read -r name; do
    [ -n "$(corr_id "$name")" ] || curl -sf "${AUTH[@]}" -H 'Content-Type: application/json' \
      -d "{\"name\": \"$name\", \"matching_algorithm\": 0}" "$URL/api/correspondents/" >/dev/null
  done

  echo "Uploading 25 documents (target.txt without a correspondent)..."
  python3 -c 'import json;[print(k + "\t" + (v or "")) for k, v in json.load(open("docs/manifest.json")).items()]' |
  while IFS=$'\t' read -r file corr; do
    args=(-F "document=@docs/$file" -F "title=${file%.txt}")
    [ -n "$corr" ] && args+=(-F "correspondent=$(corr_id "$corr")")
    curl -sf "${AUTH[@]}" "${args[@]}" "$URL/api/documents/post_document/" >/dev/null
  done
  until [ "$(curl -sf "${AUTH[@]}" "$URL/api/documents/?page_size=1" | json 'd["count"]')" -ge 25 ]; do sleep 3; done

  echo "Building the LLM index..."
  # Run as the paperless user: a root-owned index lock would break the workers.
  docker compose exec -T -u paperless webserver python3 manage.py document_llmindex rebuild >/dev/null 2>&1
fi

TARGET=$(curl -sf "${AUTH[@]}" "$URL/api/documents/?title__iexact=target" | json 'd["results"][0]["id"]')
ACME=$(corr_id "Acme Domains")
echo
echo "Target document: $TARGET. Correct correspondent: Acme Domains (id $ACME), which has exactly one"
echo "earlier, nearly identical invoice (acme-2025). Correspondent ids:"
curl -sf "${AUTH[@]}" "$URL/api/correspondents/?page_size=100" | json '"\n".join("  %s: %s (%s docs)" % (c["id"], c["name"], c["document_count"]) for c in d["results"])'

for mode in aligned misaligned; do
  curl -sf -X POST "$MOCK/mode" -d "$mode" >/dev/null
  docker compose exec -T broker redis-cli FLUSHALL >/dev/null   # drop cached suggestions
  echo
  echo "=== mock LLM mode: $mode"
  echo "GET /api/documents/$TARGET/ai_suggestions/ ->"
  curl -sf "${AUTH[@]}" "$URL/api/documents/$TARGET/ai_suggestions/" |
    json '"  correspondents: " + str(d["correspondents"]) + "   suggested_correspondents: " + str(d["suggested_correspondents"])'
  echo "Correspondent candidates in the prompt Paperless sent (in order):"
  curl -sf "$MOCK/last" | json '"  " + str(d["last_correspondent_candidates"])'
  echo "LLM tool call (webserver DEBUG log):"
  docker compose exec -T -u paperless webserver sh -c 'grep -h "LLM query result" /usr/src/paperless/data/log/paperless.log' | tail -1 |
    grep -oE "'(correspondents|matched_correspondents|correspondent_ids)': \[[^]]*\]" | sed 's/^/  /' || true
done
echo
echo "Prompts sent to the LLM are saved in ./prompts/. Clean up with: ./run.sh down"
