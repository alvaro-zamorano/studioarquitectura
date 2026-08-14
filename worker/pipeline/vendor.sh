#!/usr/bin/env bash
# three.js r128 para el visor offline. No se vendoriza en el repo: son 592 KB de
# libreria minificada que no aportan nada al historial.
#
# La version esta CLAVADA a r128 a proposito: el visor usa ExtrudeGeometry con
# huecos, ShapeGeometry y ACESFilmicToneMapping con la API de esa version.
# Subirla es un cambio que hay que probar, no un `latest`.
set -euo pipefail
cd "$(dirname "$0")"

URL="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"

if [ -s three.min.js ]; then
  echo "three.min.js ya esta ($(stat -c%s three.min.js) bytes)"
  exit 0
fi

curl -fsSL "$URL" -o three.min.js
BYTES=$(stat -c%s three.min.js)
[ "$BYTES" -gt 500000 ] || { echo "descarga sospechosa: $BYTES bytes"; rm -f three.min.js; exit 1; }
echo "three.min.js $BYTES bytes"
