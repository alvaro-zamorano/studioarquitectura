#!/usr/bin/env bash
# Arranque completo del worker desde Google Cloud Shell.
#
#   bash infra/cloudshell-arranca.sh
#
# Cloud Shell ya trae gcloud autenticado, asi que no hay nada que instalar.
# Este script hace, en orden: elegir o crear proyecto, vincular facturacion,
# activar las APIs, desplegar y COMPROBAR que el despliegue funciona.
#
# Se para y pide confirmacion antes de crear el proyecto y antes de vincular la
# facturacion. Son las dos unicas acciones con consecuencias de dinero, y una
# maquina no las decide sola.
set -euo pipefail

PROY_DEF="plano3d-milimetro"
azul()  { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
gris()  { printf '\033[0;90m%s\033[0m\n' "$*"; }
alto()  { printf '\n\033[1;33m⛔ %s\033[0m\n' "$*"; }

azul "1 · proyecto"
ACTUAL=$(gcloud config get-value project 2>/dev/null || true)
if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "(unset)" ]; then
  echo "Cloud Shell apunta a: $ACTUAL"
  read -rp "¿Usar este proyecto? [S/n] " R
  case "${R:-s}" in [Nn]*) ACTUAL="";; esac
fi
if [ -z "$ACTUAL" ] || [ "$ACTUAL" = "(unset)" ]; then
  read -rp "ID del proyecto a usar o crear [$PROY_DEF]: " ACTUAL
  ACTUAL="${ACTUAL:-$PROY_DEF}"
  if ! gcloud projects describe "$ACTUAL" >/dev/null 2>&1; then
    alto "El proyecto '$ACTUAL' no existe (o es de otra cuenta). Se intentará CREAR."
    gris "Los IDs son únicos en todo Google Cloud: si sale 'already in use', elige otro."
    read -rp "¿Crearlo? [s/N] " R
    case "${R:-n}" in [Ss]*) gcloud projects create "$ACTUAL";; *) exit 1;; esac
  fi
fi
gcloud config set project "$ACTUAL" >/dev/null
echo "proyecto: $ACTUAL"

azul "2 · facturación"
# Cloud Run tiene franja gratuita generosa, pero Google exige una cuenta de
# facturacion vinculada aunque no llegues a pagar nada. Esto no se automatiza.
if gcloud beta billing projects describe "$ACTUAL" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  echo "ya vinculada"
else
  # Se listan SOLO las abiertas. Una cuenta cerrada se vincula sin error y deja
  # el proyecto con billingEnabled=false; el fallo aparece despues, al activar
  # las APIs, con un UREQ_PROJECT_BILLING_NOT_OPEN que no dice que la culpable
  # es la cuenta. Mejor no ofrecerla siquiera.
  gcloud beta billing accounts list --filter='open=true' \
    --format='value(name,displayName)' 2>/dev/null | tee /tmp/p3d-cuentas.txt
  if [ ! -s /tmp/p3d-cuentas.txt ]; then
    alto "No tienes ninguna cuenta de facturación ABIERTA."
    gcloud beta billing accounts list --format='table(name,displayName,open)' 2>/dev/null || true
    echo
    echo "Si alguna sale con open: False, está cerrada (prueba gratuita agotada o"
    echo "tarjeta caducada). Se reactiva en el navegador, no hay comando:"
    echo "  https://console.cloud.google.com/billing"
    exit 1
  fi
  # Se valida ANTES de usarlo. La primera version de este script aceptaba
  # cualquier cosa —incluido un 's' de responder 'si' por inercia— y se lo
  # pasaba a gcloud, que devolvia un INVALID_ARGUMENT sin explicar nada.
  CTA=""
  for _ in 1 2 3; do
    read -rp "ID de la cuenta a vincular (la PRIMERA columna, formato XXXXXX-XXXXXX-XXXXXX): " CTA
    if grep -q "^${CTA}[[:space:]]" /tmp/p3d-cuentas.txt 2>/dev/null; then
      break
    fi
    alto "'$CTA' no es ninguna de las cuentas ABIERTAS de arriba."
    gris "Tiene que ser una de esas, literal. No vale 's' ni una cerrada."
    CTA=""
  done
  [ -n "$CTA" ] || { echo "tres intentos fallidos, se aborta"; exit 1; }

  NOMBRE=$(grep "^${CTA}[[:space:]]" /tmp/p3d-cuentas.txt | cut -f2- || echo "?")
  alto "Se va a VINCULAR la facturación al proyecto '$ACTUAL'."
  echo "   cuenta: $CTA  ($NOMBRE)"
  gris "Con el uso previsto no deberías pagar nada: la franja gratuita de Cloud Run"
  gris "cubre 240.000 vCPU-s y 450.000 GiB-s al mes. Pero es dinero: decides tú."
  read -rp "¿Vincular? [s/N] " R
  case "${R:-n}" in [Ss]*) gcloud beta billing projects link "$ACTUAL" --billing-account="$CTA";; *) exit 1;; esac

  # Comprobar, no confiar: el link devuelve 0 aunque la cuenta este cerrada.
  if ! gcloud beta billing projects describe "$ACTUAL" \
       --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
    alto "Vinculada pero billingEnabled sigue en false: esa cuenta esta CERRADA."
    echo "Reactivala en https://console.cloud.google.com/billing y vuelve a lanzar."
    exit 1
  fi
  echo "facturación activa"
fi

azul "3 · APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

azul "4 · despliegue"
gris "El primer build tarda ~10 min: compila LibreDWG desde fuente."
GCP_PROJECT="$ACTUAL" bash "$(dirname "$0")/deploy-cloudrun.sh"

azul "5 · lo que falta"
URL=$(gcloud run services describe plano3d-worker --region "${GCP_REGION:-europe-southwest1}" \
      --format='value(status.url)' 2>/dev/null || true)
TOK=$(gcloud secrets versions access latest --secret=plano3d-service-token 2>/dev/null || true)
cat <<TXT

Para Vercel, en https://vercel.com/new  ->  Root Directory: web

  WORKER_URL     $URL
  SERVICE_TOKEN  $TOK

Y la prueba de verdad, con un DWG tuyo (súbelo a Cloud Shell arrastrándolo):

  SERVICE_TOKEN='$TOK' ./worker/test_api.sh plano.dwg $URL

Tiene que terminar en TODAS LAS COMPROBACIONES OK. Esa prueba es la única que
detecta si la tarea de fondo se quedó sin CPU: sube un plano de verdad y espera
a que el estado llegue a revision_humana.
TXT
