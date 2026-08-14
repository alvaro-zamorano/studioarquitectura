#!/usr/bin/env bash
# Despliega el worker en Cloud Run. Scale-to-zero: se paga por segundo de CPU.
#
# Requisitos: gcloud autenticado y un proyecto con Cloud Run + Artifact Registry.
set -euo pipefail

PROY="${GCP_PROJECT:?exporta GCP_PROJECT}"
REGION="${GCP_REGION:-europe-southwest1}"     # Madrid
SVC="plano3d-worker"

gcloud builds submit worker --tag "gcr.io/$PROY/$SVC" --project "$PROY"

# --memory 2Gi: Chromium mas GEOS. Con menos, la captura muere sin decir por que.
# --timeout 900: el limite de Cloud Run. El pipeline tarda 3 s, pero los renders
#   generativos de F2 van en minutos y conviene no tener que volver aqui.
# --min-instances 0: escala a cero de verdad. El arranque en frio son ~8 s y para
#   un servicio de "subes el plano y en 24 h tienes el enlace" es irrelevante.
gcloud run deploy "$SVC" \
  --image "gcr.io/$PROY/$SVC" \
  --project "$PROY" --region "$REGION" \
  --memory 2Gi --cpu 2 --timeout 900 \
  --min-instances 0 --max-instances 5 \
  --set-env-vars WORK_ROOT=/data \
  --allow-unauthenticated

echo
echo "OJO: --allow-unauthenticated deja la API abierta. Vale para F0 con un"
echo "estudio, NO cuando haya datos de varios clientes. En F1 va detras de auth."
