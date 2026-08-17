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
  → dwg2dxf            0,41 s   LibreDWG 0.14.8580
  → extract            0,64 s   model.json   ── IDÉNTICO a la referencia
  → cobertura          0,48 s   puerta 9: toda etiqueta del plano está en el modelo
  → verify 2D          0,82 s   puertas 1-5, ambas islas
  → build3d            0,14 s   scene.json   ── IDÉNTICO a la referencia
  → verify 3D          0,17 s   TODAS LAS PUERTAS OK (1-8, ambas variantes)
  → publish            0,04 s   visor web 31 KB + offline 620 KB
                       ──────
                       2,70 s   → estado: revision_humana
```

La cadena se reproduce **desde el fichero DWG original**. El `model.json` ya no viene
dado: se reconstruye y sale idéntico.

---

## Qué se sabe sobre planos de otros estudios

Medido, no supuesto:

| Se cambia | Resultado |
|---|---|
| Nombres de capa (`POLILINEA`→`ZZQ-4471`, `01-SECC`→`CAPA-9`) | **geometría idéntica**. La detección por forma funciona |
| `0,78x1,25` escrito `0.78x1.25` | ventanas 12→2. **Lo caza la puerta 9** |
| `PUERTA 72.5` escrito `P-725` | puertas 6→2. **Lo caza la puerta 9** |
| `12,50 m2` escrito `12,50 m²` | muere en `extract`, exit 1 |

Antes de la puerta 9, los dos casos del medio pasaban con **exit 0 y las ocho puertas en
verde**: un modelo plausible al que le faltaban dos tercios de los huecos, con la puerta 8
disimulándolo mediante pasos deducidos. Ese era el fallo caro y ya no es silencioso.

---

## Estructura

```
worker/                   el motor. Contenedor. Lo que no cabe en serverless
  Dockerfile              multi-stage: compila LibreDWG y copia solo el binario
  app.py                  API HTTP (FastAPI)
  run_pipeline.py         orquestador de estados
  pipeline/               código verificado — NO se toca desde el orquestador
    pipeline.py           DWG→DXF→model.json + puertas 1-5 + superposición 2D
    verify_coverage.py    puerta 9: cobertura de etiquetas
    build_scene.py        model.json → scene.json (geometría 3D)
    openings.py           localización de vanos por rayo
    verify.py             las puertas 1-8 del 3D
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
2. **La puerta 9 es la que protege a los planos ajenos.** Las otras comprueban que lo
   extraído es *correcto*; la 9 comprueba que está *completo*. No tiene umbrales: es una
   contabilidad exacta, y busca lo que no sabemos leer en vez de medir lo que sí.
   Si un plano nuevo la hace fallar, se le enseña la convención al extractor —
   **nunca se relaja la puerta**.
3. **Nada se entrega sin la superposición 2D vista por un humano.** Es la puerta 7 y no
   se automatiza: es la única que detecta una extracción numéricamente correcta pero
   geométricamente falsa. El código la impone: ninguna ruta devuelve enlace sin `/approve`.
4. **Ningún render llega al cliente sin pasar `check_render.py`.**
5. **Ningún parámetro se ajusta contra la métrica de validación.** Si hay que tocar algo
   para que una comprobación pase, esa comprobación queda invalidada.
6. **Ninguna medida sale de una imagen generada.** La imagen es el acabado; el número
   viene del modelo.
7. **El orquestador no modifica el pipeline.** Los scripts están verificados contra el
   plano de Milímetro; se llaman como subprocesos y se adapta el orquestador, nunca al revés.

---

## Lo que falta, por orden

| | Pieza | Por qué ahora o por qué no |
|---|---|---|
| **F0.2** | App Next.js en Vercel | la cara: subir, ver estado, aprobar, compartir |
| **F0.3** | Segundo DWG de otro estudio | los nombres de capa ya no importan; lo que rompe son las convenciones de texto, y ahora la puerta 9 las declara en vez de tragarlas |
| F1 | Supabase + RLS, puertas persistidas | cuando haya más de un estudio |
| F1 | Cola (QStash) | cuando entren los renders, que tardan minutos |
| F2 | fal.ai + ControlNet-depth | bloqueado por `FAL_KEY` |
| F3 | Estudio de capacidad | *"¿cabe una cama de 150 en DORM 2?"* — esto no lo hace nadie |

---

## Pendiente del estudio (Milímetro)

- Etiquetas de carpintería del reformado → quitan los 2 pasos deducidos
- Altura libre del reformado → hoy es un supuesto (2,72 m)
- La ventana `0,60x2,10+T`: luz medida 0,745 m contra etiqueta 0,60 m
