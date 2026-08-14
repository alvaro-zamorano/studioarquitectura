# Worker del pipeline plano->3D.
#
# Aqui vive TODO lo que no cabe en una funcion serverless: el binario de LibreDWG,
# GEOS/shapely y Chromium. Es la razon de ser de este contenedor.
#
# LibreDWG es GPL. Se invoca como EJECUTABLE SEPARADO (dwg2dxf via subprocess),
# nunca enlazado como libreria: por eso se copia solo el binario a la imagen
# final. Esa frontera mantiene el resto del codigo fuera del alcance de la GPL.
# No se cambia sin consultar con asesoria (riesgo 3 de ARQUITECTURA-producto.md).

# ---------------------------------------------------------------- 1. LibreDWG
# Se compila desde fuente a proposito: libredwg-tools NO esta en los repos de
# Ubuntu, y la version de Debian va por detras del formato DWG. Compilar fija la
# version y evita depender de que un paquete exista.
# Verificado: 0.14.8580 lee el AC1032 (DWG 2018) de Milimetro en 0,1 s.
FROM debian:bookworm-slim AS libredwg

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential autoconf automake libtool texinfo pkg-config git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG LIBREDWG_REF=master
RUN git clone --depth 1 --branch ${LIBREDWG_REF} https://github.com/LibreDWG/libredwg.git /src
WORKDIR /src
RUN sh autogen.sh \
    && ./configure --disable-bindings --disable-python --disable-shared --enable-release \
    && make -j"$(nproc)" \
    && strip programs/dwg2dxf

# ---------------------------------------------------------------- 2. Runtime
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    DEBIAN_FRONTEND=noninteractive \
    WORK_ROOT=/data

# El binario, y nada mas del builder. Es estatico: no arrastra libredwg.so.
COPY --from=libredwg /src/programs/dwg2dxf /usr/local/bin/dwg2dxf

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgeos-c1v5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dwg2dxf --version | head -1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo chromium. ~300 MB, es el precio de generar la superposicion 2D y las
# imagenes de control sin display.
RUN playwright install --with-deps chromium

COPY . .
RUN bash pipeline/vendor.sh && mkdir -p ${WORK_ROOT}

# Cloud Run inyecta PORT. En local vale 8080.
ENV PORT=8080
EXPOSE 8080

# Un worker, no varios: el trabajo pesado es subprocess y C (GEOS, Chromium),
# no Python puro. Escalar es escalar instancias.
CMD exec uvicorn app:api --host 0.0.0.0 --port ${PORT} --workers 1
