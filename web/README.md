# web · la cara

Next.js. Cuatro pantallas: subir, estado, revisar, compartir.

```bash
npm install
cp .env.example .env.local     # WORKER_URL y SERVICE_TOKEN
npm run dev
```

---

## Lo único que hay que entender del diseño

**El token de servicio no sale del servidor.** Todas las llamadas al worker pasan por
route handlers (`app/api/**`) que añaden la credencial. `lib/worker.ts` es el único sitio
que la lee. Si aparece un `fetch` al worker dentro de un componente `'use client'`, es un
bug de seguridad, no un atajo.

Comprobado en el e2e: se registran todas las respuestas que recibe el navegador y se
busca el token en ellas. Tienen que ser cero.

**Dos zonas, como en el worker.** `/jobs*` es el panel del estudio. `/p/{token}` es el
enlace del cliente final: abierto, sin cuenta, y no existe hasta que alguien ha aprobado
la superposición.

**Cuidado al leer variables de entorno.** Next sustituye `process.env.ALGO` por su valor
literal *durante el build*. Con notación de punto, el token queda congelado al del momento
de compilar y un `next start` con la variable puesta no sirve de nada. Por eso
`lib/worker.ts` lee con corchetes. En Vercel no se nota porque las variables están
presentes al construir; en un contenedor, sí — costó un 401 descubrirlo.

---

## La prueba

```bash
# en otra terminal: el worker con SERVICE_TOKEN puesto
npm run build && npm start
SERVICE_TOKEN=<el-mismo> node e2e.mjs ruta/al/plano.dwg
```

Trece comprobaciones con navegador de verdad: subida, los siete pasos en pantalla, la
superposición dentro del iframe, que **no haya enlace antes de aprobar**, el visor
arrancando en el enlace público, el panel colapsado a 390 px, y que el token no se filtre.

Una de ellas se declara **NO COMPROBADA** cuando el entorno no tiene salida a cdnjs: el
visor alojado carga three.js de ahí. Se declara en vez de darse por buena, que es la
diferencia entre una prueba y un adorno.

---

## Despliegue en Vercel

Framework Next.js (autodetectado). Root Directory `web`. Dos variables de entorno:

| | |
|---|---|
| `WORKER_URL` | la URL del contenedor desplegado |
| `SERVICE_TOKEN` | el mismo valor que lleva el worker |

**Ojo con el plan.** Hobby está restringido a uso *no comercial*, y su definición incluye
«receiving payment to create, update, or host the site». El día que Milímetro pague por
esto, hace falta Pro — aunque la web no cobre nada a nadie.

---

## Falta `package-lock.json`

No está en el repo a propósito, y hay que añadirlo: es lo que fija el árbol transitivo.
Se genera al clonar.

```bash
cd web && npm install && npm audit
git add package-lock.json && git commit -m "web: lockfile"
```

Importa más de lo habitual porque este proyecto arrancó con `next@15.1.6`, elegido de
memoria, que tenía una vulnerabilidad **crítica** (`9.3.4-canary.0 - 16.3.0-preview.10`).
Está en 16.3.1 y `npm audit` da cero. Sin lockfile, esa garantía dura hasta la siguiente
instalación.
