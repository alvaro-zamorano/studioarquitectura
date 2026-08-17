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
    alto "El proyecto '$ACTUAL' no existe. Se va a CREAR."
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
  CUENTAS=$(gcloud beta billing accounts list --format='value(name,displayName)' 2>/dev/null || true)
  if [ -z "$CUENTAS" ]; then
    alto "No hay ninguna cuenta de facturación en esta sesión."
    echo "Créala en https://console.cloud.google.com/billing y vuelve a lanzar esto."
    exit 1
  fi
  echo "$CUENTAS"
  read -rp "ID de la cuenta a vincular (la primera columna): " CTA
  alto "Se va a VINCULAR la facturación de '$CTA' al proyecto '$ACTUAL'."
  gris "Con el uso previsto no deberías pagar nada: la franja gratuita de Cloud Run"
  gris "cubre 240.000 vCPU-s y 450.000 GiB-s al mes. Pero es dinero: decides tú."
  read -rp "¿Vincular? [s/N] " R
  case "${R:-n}" in [Ss]*) gcloud beta billing projects link "$ACTUAL" --billing-account="$CTA";; *) exit 1;; esac
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
