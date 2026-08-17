# De motor a aplicación · plan

Objetivo original, sin rebajarlo: **un estudio de arquitectura mete el fichero de un
plano y su cliente final ve, en el móvil, cómo va a quedar la reforma** — con la
volumetría navegable y con imágenes de acabado que no se inventan la geometría.

Este documento va de cómo llegar ahí desde lo que hay hoy. Cada fase tiene un criterio
de terminación **comprobable por máquina**. Si un criterio no se puede comprobar con un
comando, está mal escrito y hay que reformularlo, no aprobarlo a ojo.

---

## Punto de partida (verificado hoy)

```
DWG → dwg2dxf → extract → cobertura(9) → verify2D(1-5) → build3D → verify3D(1-8) → visor
                                                                            2,70 s
```

- Nueve puertas de máquina, una humana. El código impide saltarse la humana.
- La cadena se reproduce desde el DWG original: `model.json` y `scene.json` salen idénticos.
- Detección de capas por forma: probada renombrándolas, geometría idéntica.
- Convenciones de texto ajenas: la puerta 9 las declara en vez de tragarlas.

**Lo que NO hay:** nada desplegado. El motor corre en una máquina y se invoca a mano.
No hay web, ni base de datos, ni renders generativos, ni multi-estudio.

---

## Fase 1 · El motor, vivo

Un contenedor en producción con URL propia. Sin esto, todo lo demás no tiene dónde apoyarse.

**Qué se hace:** `infra/deploy-cloudrun.sh` (o Fly, es reversible). Volumen persistente
en `/data`. La API **detrás de un token de servicio** — hoy `--allow-unauthenticated`
la deja abierta, y eso vale para probar, no para tener datos de un cliente dentro.

**Terminado cuando:**

| check | cómo |
|---|---|
| `http_status` | `GET /health` devuelve 200 y `dwg2dxf: true` |
| `command_exit_zero` | subir el DWG de LM20 por `curl` termina en `revision_humana` |
| `http_status` | `GET /p/{token}` de un trabajo aprobado devuelve 200 |
| `http_status` | la misma ruta con un token inventado devuelve 404 |
| `command_exit_zero` | `POST /jobs` sin cabecera de servicio devuelve 401 |

**Coste:** Cloud Run scale-to-zero, unos pocos € al mes con este volumen.
**Esfuerzo:** una tarde. El Dockerfile ya está y compila LibreDWG.

---

## Fase 2 · La cara

Next.js en Vercel. Cuatro pantallas y ni una más:

1. **Subir** — arrastras DWG (+ PDF opcional). Sube firmado, no pasa por la función.
2. **Estado** — los pasos con su tiempo y la salida íntegra de cada verificador.
   Esto no es debug: es el argumento de venta. Cuando el estudio pregunte de dónde sale
   un número, la respuesta está en pantalla.
3. **Revisar** — la superposición 2D a pantalla completa y **un solo botón**: aprobar.
   Con el aviso de qué está mirando y por qué nadie más puede hacerlo.
4. **Compartir** — el enlace del cliente, el fichero offline para WhatsApp, y la tabla
   de huecos con su estado (verificado / aproximado / deducido).

**La decisión que importa:** la pantalla 3 no se puede automatizar ni "recordar la
preferencia". Es la puerta 7. Un checkbox de *no volver a preguntar* mata el servicio.

**Terminado cuando:**

| check | cómo |
|---|---|
| `http_status` | la URL de producción devuelve 200 |
| `command_exit_zero` | Playwright: subir DWG → esperar `revision_humana` → aprobar → abrir el enlace y comprobar `window.__ready === true` |
| `file_contains` | el HTML de la pantalla 4 contiene el número de huecos deducidos |
| `command_exit_zero` | Playwright a 390 px: el visor renderiza y el panel se colapsa |

**Coste:** Vercel Hobby mientras sea uso propio; Pro (20 $/mes) el día que se factura.
**Esfuerzo:** 2-3 días.

---

## Fase 3 · El plano de otro estudio ⚠️

**Esta fase decide si esto es un producto o un servicio artesanal.** Va antes de la base
de datos y antes de los renders. Un email a un despacho conocido y un DWG cualquiera.

Ahora se sabe exactamente qué mirar, porque está medido: los nombres de capa son
irrelevantes, y lo que rompe son las convenciones de texto. La puerta 9 las señala con
nombre y apellidos.

**Terminado cuando:**

| check | cómo |
|---|---|
| `command_exit_zero` | un DWG ajeno recorre las nueve puertas sin tocar una línea de código |
| `file_contains` | si falla, el informe de la puerta 9 nombra la convención exacta que falta |
| `agent_judgment` | la superposición 2D del plano ajeno la valida un humano |

Si hace falta enseñar convenciones nuevas al extractor, **cada una entra con su caso de
prueba** — el `model.json` de ese plano se convierte en la segunda referencia de
regresión del CI. Ahí empieza `studio_layer_profiles`: lo aprendido de cada despacho es
el activo que se acumula y lo que hace caro cambiarse a otra herramienta.

**Esfuerzo:** 1 día por plano si las convenciones son razonables. Impredecible si no.

---

## Fase 4 · Multi-estudio

Solo cuando haya un segundo estudio de verdad. Antes es resolver un problema inexistente.

Supabase: Postgres con RLS por `studio_id`, Storage para los ficheros, Auth por magic
link. Y la tabla que es el producto:

```sql
gates (variant_id, n, nombre, pasa, detalle, medido_en)
```

Cada `scene.json` generado deja sus nueve filas. Si mañana una versión del pipeline rompe
algo, se ve en la tabla antes de que lo vea un cliente. **Es la trazabilidad de la medida
en el tiempo**, y no la enseña ningún competidor.

**Terminado cuando:**

| check | cómo |
|---|---|
| `command_exit_zero` | el estudio A no puede leer ni un registro del estudio B (test SQL con dos JWT) |
| `command_exit_zero` | un trabajo completo deja 9 filas en `gates` |
| `http_status` | el enlace público sigue funcionando sin sesión |

**Coste:** Supabase Pro ~25 $/mes; el free tier aguanta el piloto.
**Esfuerzo:** 3-4 días.

---

## Fase 5 · Las imágenes

Lo que pedías al principio: que el cliente final vea el acabado, no una maqueta blanca.

Ya está construido el 80%: `shot_brief.py` fabrica cámara y prompt desde los datos —
inventario por pared, muros ciegos nombrados explícitamente — y `check_render.py`
verifica la imagen proyectando los huecos con la misma cámara.

**Lo que falta es el condicionamiento geométrico real: ControlNet-depth.** Bloqueado por
`FAL_KEY`. Sin él, el generativo depende del verificador para descartar, y descarta
bastante: en la primera ronda, 3 de 6 usables y una ventana inventada.

Dos cosas que van desde el primer día porque después no se ponen:

- **Dos proveedores detrás de la misma interfaz.** El filtro de moderación de uno nos
  tumbó 2 de 6 generaciones sobre una habitación vacía. Depender de uno solo es regalar
  el servicio a su política de contenidos.
- **Las imágenes rechazadas se guardan.** La tasa de descarte por estudio y por modelo es
  una métrica de negocio, no un log.

**Terminado cuando:**

| check | cómo |
|---|---|
| `command_exit_zero` | 20 generaciones seguidas, `check_render.py` acepta ≥80% y **0 con hueco inventado** |
| `file_contains` | cada imagen entregada tiene su veredicto y sus checks en `renders` |
| `command_exit_zero` | ninguna ruta sirve una imagen sin veredicto `aceptada` |

Ese 80% es un objetivo comercial, no un umbral que se toque para aprobar. El **0 huecos
inventados** sí es innegociable: una lámina con una ventana que no existe, enseñada en una
reunión, cuesta más que todo lo que ahorra el generativo.

**Coste:** por imagen, con la tasa de descarte incluida.
**Esfuerzo:** 2-3 días una vez haya key.

---

## Fase 6 · Lo que no hace nadie

**Estudio de capacidad.** *"¿Cabe una cama de 150 en el dormitorio 2 descontando el
barrido de la puerta y 80 cm de paso?"* — con un número y el rectángulo dibujado encima
de la planta.

Cedreo no lo hace. Ninguna herramienta de visualización lo hace, porque todas parten de
un dibujo y nosotros partimos de una **medida verificada**. Es lo único de esta lista que
no se puede copiar sin construir antes las nueve puertas.

**Terminado cuando:**

| check | cómo |
|---|---|
| `command_exit_zero` | dado un mueble de A×B, devuelve si cabe y dónde, o por qué no |
| `command_exit_zero` | 10 casos con respuesta conocida a mano: 10 aciertos |

---

## Orden y por qué

```
1. Motor vivo        ──┐
2. Cara              ──┤  esto ya es un servicio vendible
3. PLANO AJENO ⚠️    ──┘  y esto decide si es un producto
                        │
4. Multi-estudio       ─┤  solo si hay segundo cliente
5. Imágenes            ─┤  solo con FAL_KEY
6. Capacidad           ─┘  el foso
```

**Fases 1 y 2 se pueden hacer en paralelo con la 3**, porque la 3 depende de que llegue
un email. Lo que no se puede es saltarse la 3 y ponerse con la 4: montar auth, RLS y
colas sobre una extracción que solo funciona con un despacho es construir sobre arena.

---

## La landing, en su sitio

Va con la fase 2 y vende **el servicio, no la plataforma**:

> *Mándanos el DWG. En 24 h tienes un enlace que tu cliente abre en el móvil, con las
> superficies contrastadas contra tu propio plano.*

Eso se cumple hoy. *"Sube tu plano y en 30 segundos"* no se cumple hasta la fase 3, y
prometerlo antes es la vía rápida a un entregable mal medido con tu nombre encima.

El argumento que nadie más puede poner en una landing es el número: **11 de 12 huecos
contrastados contra la etiqueta del propio plano, error 0,0 mm; el que no cuadra está
declarado y a la vista.**

---

## Coste de infraestructura, en régimen

| | |
|---|---|
| Cloud Run scale-to-zero | unos pocos €/mes |
| Vercel | 0 → 20 $/mes al facturar |
| Supabase | 0 → 25 $/mes en fase 4 |
| Cola (QStash) | free tier al principio |
| Generativo | por imagen, descartes incluidos |

Por debajo de 60 $/mes hasta que haya volumen. **El coste real no es la infraestructura:
es la revisión humana de la puerta 7.** Por eso hay que medir cuánto tarde de verdad con
5 proyectos antes de fijar precio — y por eso el verificador automático de renders no es
un lujo, es lo que mantiene el margen.

---

## Riesgos, por probabilidad de matar el proyecto

1. **El plano ajeno.** Mitigado a medias: capas resueltas, convenciones de texto
   detectadas pero no resueltas. Se cierra en la fase 3 o no se cierra.
2. **La puerta humana no escala** si cada proyecto pide 20 minutos. Hay que cronometrarla
   con 5 proyectos reales antes de poner precio.
3. **GPL de LibreDWG.** Se invoca como ejecutable separado y el Dockerfile copia solo el
   binario. Es la vía habitual para no contaminar, pero no soy abogado: esto lo confirma
   asesoría antes de vender, no después.
4. **Dependencia del proveedor de imagen.** Ya nos tumbó 2 de 6 generaciones. Dos
   proveedores desde el primer día.

---

## Deuda conocida, escrita para que no se olvide

- El repo está **público** y va a contener datos de cliente.
- `render_brief.py` lleva la ruta `/home/claude/plano3d/LM20-3d.html` clavada.
- `verify.yml` no lo puede subir el conector de GitHub (permiso `Workflows`); se añade a mano.
- Tres PAT pasaron por el chat y hay que rotarlos.
- Pendiente de Milímetro: carpinterías del reformado, altura libre del reformado, y la
  ventana `0,60x2,10+T` cuya luz medida (0,745) no cuadra con su etiqueta (0,60).
