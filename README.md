# plano-3d · el sistema

Servicio de **medición verificada** a partir del DWG del estudio, con volumetría 3D
navegable como entregable para el cliente final.

Lo que se vende no es el 3D. Es que cada número que ve el cliente sale del plano del
estudio y está contrastado contra la etiqueta de carpintería de ese mismo plano, con el
error medido. El 3D es lo que hace comprensible ese número a alguien que no lee planos.

---

## Estado real, medido

```
Luis_Mitjans_-_IA.dwg (AC1032, DWG 2018)
  → dwg2dxf            0,46 s   LibreDWG 0.14.8580
  → extract            0,82 s   model.json   ── IDÉNTICO a la referencia
  → verify 2D          1,13 s   puertas 1-5, ambas islas
  → build3d            0,20 s   scene.json   ── IDÉNTICO a la referencia
  → verify 3D          0,25 s   TODAS LAS PUERTAS OK (1-8, ambas variantes)
  → publish            0,05 s   visor web 31 KB + offline 620 KB
                       ──────
                       2,91 s   → estado: revision_humana
```

La cadena se reproduce **desde el fichero DWG original**. El `model.json` ya no viene
dado: se reconstruye y sale idéntico.

---

## Estructura

```
worker/                   el motor. Contenedor. Lo que no cabe en serverless
  Dockerfile              multi-stage: compila LibreDWG y copia solo el binario
  app.py                  API HTTP (FastAPI)
  run_pipeline.py         orquestador de estados
  pipeline/               código verificado — NO se toca desde el orquestador
    pipeline.py           DWG→DXF→model.json + puertas 1-5 + superposición 2D
    build_scene.py        model.json → scene.json (geometría 3D)
    openings.py           localización de vanos por rayo
    verify.py             las 8 puertas
    publish.py            scene.json → visor web + visor offline
    shot_brief.py         cámara + brief de render desde los datos
    check_render.py       verificador de la imagen generada
    vendor.sh             baja three.js (no se vendoriza en el repo)
infra/                    despliegue del worker
web/                      la cara. Next.js en Vercel   ← F0.2, aún no
db/                       esquema Supabase             ← F1, aún no
```

---

## La API

```
POST /jobs                 multipart: dwg=<fichero> [pdf=<fichero>]   → 202 {id}
GET  /jobs/{id}            estado + salida íntegra de cada verificador
GET  /jobs/{id}/overlay    la superposición 2D   ← lo que mira el humano
POST /jobs/{id}/approve    pasa la puerta 7 y SOLO entonces devuelve el enlace
GET  /p/{token}/           el visor
GET  /p/{token}/offline    el visor autocontenido, para correo o WhatsApp
```

Comprobado: antes de `/approve` la respuesta **no trae enlace**. Un token inventado da 404.

---

## Arrancar en local

```bash
cd worker
pip install -r requirements.txt
playwright install chromium
bash pipeline/vendor.sh

# dwg2dxf NO está en los repos de Ubuntu. En Debian/macOS:
#   apt-get install libredwg-tools   |   brew install libredwg
# Si no está, se compila (es lo que hace el Dockerfile):
#   git clone --depth 1 https://github.com/LibreDWG/libredwg && cd libredwg
#   sh autogen.sh && ./configure --disable-bindings --enable-release && make -j

WORK_ROOT=./data uvicorn app:api --port 8080
```

Sin servidor, un solo plano:

```bash
WORK_ROOT=./data python3 run_pipeline.py plano.dwg
```

Con Docker:

```bash
docker build -t plano3d-worker worker/
docker run -p 8080:8080 -v $PWD/data:/data plano3d-worker
```

---

## Las reglas que no se negocian

1. **`verify.py` en verde o no se mergea.** Corre en CI en cada commit.
2. **Nada se entrega sin la superposición 2D vista por un humano.** Es la puerta 7 y no
   se automatiza: es la única que detecta una extracción numéricamente correcta pero
   geométricamente falsa. El código la impone: ninguna ruta devuelve enlace sin `/approve`.
3. **Ningún render llega al cliente sin pasar `check_render.py`.**
4. **Ningún parámetro se ajusta contra la métrica de validación.** Si hay que tocar algo
   para que una comprobación pase, esa comprobación queda invalidada.
5. **Ninguna medida sale de una imagen generada.** La imagen es el acabado; el número
   viene del modelo.
6. **El orquestador no modifica el pipeline.** Los scripts están verificados contra el
   plano de Milímetro; se llaman como subprocesos y se adapta el orquestador, nunca al revés.

---

## Lo que falta, por orden

| | Pieza | Por qué ahora o por qué no |
|---|---|---|
| **F0.2** | App Next.js en Vercel | la cara: subir, ver estado, aprobar, compartir |
| **F0.3** | Segundo DWG de otro estudio | **el riesgo que mata el proyecto.** Validado contra un solo fichero |
| F1 | Supabase + RLS, puertas persistidas | cuando haya más de un estudio |
| F1 | Cola (QStash) | cuando entren los renders, que tardan minutos |
| F2 | fal.ai + ControlNet-depth | bloqueado por `FAL_KEY` |
| F3 | Estudio de capacidad | *"¿cabe una cama de 150 en DORM 2?"* — esto no lo hace nadie |

**F0.3 va antes que F1.** Un DWG de otro despacho cuesta un email y decide si esto es un
producto o una pieza artesanal muy buena.

---

## Pendiente del estudio (Milímetro)

- Etiquetas de carpintería del reformado → quitan los 2 pasos deducidos
- Altura libre del reformado → hoy es un supuesto (2,72 m)
- La ventana `0,60x2,10+T`: luz medida 0,745 m contra etiqueta 0,60 m
