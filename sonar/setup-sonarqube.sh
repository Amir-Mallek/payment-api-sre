#!/usr/bin/env bash
# Configures a fresh SonarQube instance: quality profile, quality gate, project and analysis token.
# Prints the token on stdout (everything else goes to stderr).
#   SONAR_HOST_URL=http://localhost:9000 ./sonar/setup-sonarqube.sh
set -euo pipefail
HOST="${SONAR_HOST_URL:-http://localhost:9000}"
NEW_PASSWORD="${SONAR_ADMIN_PASSWORD:-Tp2-Sre-Admin-2026!}"
PROJECT_KEY="${SONAR_PROJECT_KEY:-payment-api}"
GATE="TP-SRE-Gate"
PROFILE="TP-SRE-Python"
log() { echo "[sonar-setup] $*" >&2; }

log "waiting for SonarQube at $HOST"
until curl -sf "$HOST/api/system/status" | grep -q '"status":"UP"'; do sleep 5; done

# Fresh instances ship with admin/admin; switch to a strong password once.
if curl -sf -u admin:admin "$HOST/api/authentication/validate" | grep -q '"valid":true'; then
  curl -sf -u admin:admin -X POST "$HOST/api/users/change_password" \
    --data-urlencode login=admin --data-urlencode previousPassword=admin --data-urlencode "password=$NEW_PASSWORD"
fi
AUTH=(-u "admin:$NEW_PASSWORD")
api() { curl -sf "${AUTH[@]}" -X POST "$HOST/api/$1" "${@:2}"; }

log "quality profile $PROFILE = Sonar way + every bug / vulnerability / security hotspot rule"
SONAR_WAY=$(curl -sf "${AUTH[@]}" "$HOST/api/qualityprofiles/search?language=py&qualityProfile=Sonar%20way" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['profiles'][0]['key'])")
PROFILE_KEY=$(api qualityprofiles/copy --data-urlencode "fromKey=$SONAR_WAY" --data-urlencode "toName=$PROFILE" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])")
api qualityprofiles/activate_rules --data-urlencode "targetKey=$PROFILE_KEY" --data-urlencode languages=py \
  --data-urlencode "types=BUG,VULNERABILITY,SECURITY_HOTSPOT" >/dev/null
api qualityprofiles/set_default --data-urlencode language=py --data-urlencode "qualityProfile=$PROFILE"

log "quality gate $GATE"
api qualitygates/create --data-urlencode "name=$GATE" >/dev/null
# New gates come with default conditions: drop them so the gate contains exactly the rules below.
curl -sf "${AUTH[@]}" "$HOST/api/qualitygates/show?name=$GATE" \
  | python3 -c "import json,sys; [print(c['id']) for c in json.load(sys.stdin)['conditions']]" \
  | while read -r id; do api qualitygates/delete_condition --data-urlencode "id=$id"; done
condition() { api qualitygates/create_condition --data-urlencode "gateName=$GATE" \
  --data-urlencode "metric=$1" --data-urlencode "op=$2" --data-urlencode "error=$3" >/dev/null; }
# Required by the assignment (new code, and overall code because CI analyses start from an empty instance):
condition new_coverage LT 85                     # coverage < 85% -> fail
condition coverage LT 85
condition new_security_hotspots_reviewed LT 100  # a single unreviewed hotspot -> fail
condition security_hotspots_reviewed LT 100
condition new_duplicated_lines_density GT 3      # duplication > 3% -> fail
condition duplicated_lines_density GT 3
# No bug and no vulnerability (rating worse than A).
condition new_reliability_rating GT 1
condition new_security_rating GT 1
condition reliability_rating GT 1
condition security_rating GT 1
api qualitygates/set_as_default --data-urlencode "name=$GATE"

log "project $PROJECT_KEY and analysis token"
api projects/create --data-urlencode "project=$PROJECT_KEY" --data-urlencode "name=Payment API" >/dev/null
api user_tokens/generate --data-urlencode "name=ci-$(date +%s)" --data-urlencode type=GLOBAL_ANALYSIS_TOKEN \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])"
