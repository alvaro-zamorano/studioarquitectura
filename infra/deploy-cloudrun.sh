#!/usr/bin/env bash
# Despliega el worker en Cloud Run. Scale-to-zero: se paga por segundo de CPU.
#
#   GCP_PROJECT=mi-proyecto ./infra/deploy-cloudrun.sh
#
# Requisitos: gcloud autenticado, Cloud Run + Artifact Registry + Secret Manager.
set -euo pipefail

PROY="${GCP_PROJECT:?exporta GCP_PROJECT}"
REGION="${GCP_REGION:-europe-southwest1}"     # Madrid
SVC="plano3d-worker"
SECRETO="plano3d-service-token"

# --- el token del panel ------------------------------------------------------
# Va en Secret Manager, no en una variable de entorno del despliegue: las env
# vars de Cloud Run se ven en la consola y en `gcloud run services describe`.
if ! gcloud secrets describe "$SECRETO" --project "$PROY" >/dev/null 2>&1; then
  echo "creando el secreto $SECRETO"
  head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' \
    | gcloud secrets create "$SECRETO" --project "$PROY" --data-file=- --replication-policy=automatic
  echo "token generado. Para leerlo:"
  echo "  gcloud secrets versions access latest --secret=$SECRETO --project=$PROY"
fi

gcloud builds submit worker --tag "gcr.io/$PROY/$SVC" --project "$PROY"

# --memory 2Gi: Chromium mas GEOS. Con menos, la captura muere sin decir por que.
# --timeout 900: el limite de Cloud Run. El pipeline tarda 3 s, pero los renders
#   generativos de F2 van en minutos y conviene no tener que volver aqui.
# --min-instances 0: escala a cero de verdad. El arranque en frio son ~8 s y para
#   un servicio de "subes el plano y en 24 h tienes el enlace" es irrelevante.
# --allow-unauthenticated: NECESARIO y correcto. El enlace que abre el cliente
#   final no puede pedir credenciales de Google. Lo que protege el panel es el
#   token de servicio dentro de la aplicacion, no la capa de IAM. Si el secreto
#   no llega, la app devuelve 503 en /jobs* en vez de quedarse abierta.
gcloud run deploy "$SVC" \
  --image "gcr.io/$PROY/$SVC" \
  --project "$PROY" --region "$REGION" \
  --memory 2Gi --cpu 2 --timeout 900 \
  --min-instances 0 --max-instances 5 \
  --set-env-vars WORK_ROOT=/data \
  --set-secrets "SERVICE_TOKEN=${SECRETO}:latest" \
  --allow-unauthenticated

URL=$(gcloud run services describe "$SVC" --project "$PROY" --region "$REGION" \
      --format='value(status.url)')
echo
echo "desplegado en $URL"

# --- comprobacion, no confianza ---------------------------------------------
echo "comprobando que el panel ha quedado protegido..."
PROT=$(curl -s "$URL/health" | python3 -c "import json,sys;print(json.load(sys.stdin).get('panel_protegido'))")
if [ "$PROT" != "True" ]; then
  echo "FALLA: /health dice panel_protegido=$PROT. El secreto no ha llegado al contenedor."
  exit 1
fi
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/jobs")
if [ "$CODE" != "401" ] && [ "$CODE" != "422" ]; then
  echo "FALLA: POST /jobs sin credencial devuelve $CODE, esperaba 401."
  exit 1
fi
echo "OK: panel protegido y /jobs rechaza sin credencial."
echo
echo "Prueba completa (12 comprobaciones), con un DWG de verdad:"
echo "  SERVICE_TOKEN=\$(gcloud secrets versions access latest --secret=$SECRETO --project=$PROY) \\"
echo "    ./worker/test_api.sh ruta/al/plano.dwg $URL"
