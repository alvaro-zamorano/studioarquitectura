#!/usr/bin/env bash
# Prueba de las dos zonas de la API.  ./test_api.sh ruta/al/plano.dwg [url]
#
# Sin URL arranca un worker local en el 8215. Con URL prueba contra el desplegado:
#     SERVICE_TOKEN=... ./test_api.sh plano.dwg https://plano3d-worker-xxx.run.app
#
# Es el criterio de terminacion de la fase 1 convertido en comando. Doce
# comprobaciones, todas de codigo HTTP: no hay nada que interpretar a ojo.
#
# La distincion que prueba, y que es la que sostiene el modelo de negocio:
#   el PANEL exige credencial de servicio
#   la ENTREGA al cliente final no, porque el cliente no tiene cuenta
#   y el enlace NO EXISTE hasta que un humano ha aprobado la superposicion
set -uo pipefail

DWG="${1:?uso: ./test_api.sh ruta/al/plano.dwg [url-base]}"
BASE="${2:-}"
TOKEN="${SERVICE_TOKEN:-s3cr3to-de-prueba}"
H="Authorization: Bearer $TOKEN"
FALLOS=0

code() { curl -s --noproxy '*' -o /dev/null -w '%{http_code}' "$@"; }
body() { curl -s --noproxy '*' "$@"; }

esperado() {   # esperado <etiqueta> <obtenido> <esperado>
  if [ "$2" = "$3" ]; then
    printf "  OK    %-26s %s\n" "$1" "$2"
  else
    printf "  FALLA %-26s %s (esperaba %s)\n" "$1" "$2" "$3"
    FALLOS=$((FALLOS + 1))
  fi
}

SRV=""
if [ -z "$BASE" ]; then
  BASE="localhost:8215"
  SERVICE_TOKEN="$TOKEN" WORK_ROOT="${WORK_ROOT:-/tmp/p3d-test}" \
    uvicorn app:api --port 8215 >/tmp/p3d-test.log 2>&1 &
  SRV=$!
  sleep 6
fi
limpia() { [ -n "$SRV" ] && kill "$SRV" 2>/dev/null; }
trap limpia EXIT

echo "── panel: exige credencial ─────────────────────"
esperado "POST /jobs sin cabecera"  "$(code -X POST -F "dwg=@$DWG" "$BASE/jobs")" 401
esperado "POST /jobs token erroneo" "$(code -H 'Authorization: Bearer no' -X POST -F "dwg=@$DWG" "$BASE/jobs")" 401

ID=$(body -H "$H" -X POST -F "dwg=@$DWG" "$BASE/jobs" \
     | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
[ -n "$ID" ] || { echo "  FALLA no se ha creado el trabajo"; exit 1; }
printf "  OK    %-26s %s\n" "POST /jobs token bueno" "$ID"

esperado "approve prematuro" "$(code -H "$H" -X POST "$BASE/jobs/$ID/approve")" 409

for _ in $(seq 1 30); do
  S=$(body -H "$H" "$BASE/jobs/$ID" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])")
  case "$S" in revision_humana|fallo) break;; esac
  sleep 2
done
esperado "las 9 puertas" "$S" revision_humana

esperado "GET /jobs sin cabecera"   "$(code "$BASE/jobs/$ID")" 401
esperado "GET overlay sin cabecera" "$(code "$BASE/jobs/$ID/overlay")" 401
esperado "GET overlay con cabecera" "$(code -H "$H" "$BASE/jobs/$ID/overlay")" 200

E=$(body -H "$H" "$BASE/jobs/$ID" | python3 -c "import json,sys;print(json.load(sys.stdin).get('enlace','(ninguno)'))")
esperado "enlace ANTES de aprobar" "$E" "(ninguno)"

echo "── la puerta humana ────────────────────────────"
T=$(body -H "$H" -X POST "$BASE/jobs/$ID/approve" \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('enlace',''))")
[ -n "$T" ] || { echo "  FALLA approve no ha devuelto enlace"; exit 1; }
printf "  OK    %-26s %s\n" "approve" "$T"

echo "── entrega: abierta para el cliente ────────────"
esperado "visor sin cabecera"   "$(code "$BASE$T")" 200
esperado "offline sin cabecera" "$(code "$BASE${T}offline")" 200
esperado "token inventado"      "$(code "$BASE/p/deadbeefdeadbeef/")" 404
esperado "/health abierta"      "$(code "$BASE/health")" 200

echo
if [ "$FALLOS" -eq 0 ]; then
  echo "TODAS LAS COMPROBACIONES OK"
  exit 0
fi
echo "$FALLOS COMPROBACIONES FALLAN"
exit 1
