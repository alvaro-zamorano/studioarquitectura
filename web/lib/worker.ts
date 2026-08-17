// Único punto por el que se habla con el worker.
//
// El token de servicio vive SOLO aquí, en el servidor. El navegador nunca lo ve:
// por eso existe esta app y no una llamada directa desde el cliente al worker.
// Si algún día aparece un `fetch` al worker dentro de un componente 'use client',
// es un bug de seguridad, no un atajo.
//
// OJO con cómo se lee el entorno. Next SUSTITUYE `process.env.ALGO` por su valor
// literal durante el build, así que si se escribe con punto, el token queda
// congelado al del momento de compilar — y un `next start` con la variable puesta
// no sirve de nada. Con corchetes no lo inlinea y se lee en cada petición.
// En Vercel no se nota porque las variables están presentes al construir; en un
// contenedor, sí: costó un 401 descubrirlo.
const env = (k: string): string => process.env[k] ?? '';

function base(): string {
  return env('WORKER_URL') || 'http://127.0.0.1:8080';
}

export function configurado(): boolean {
  return Boolean(env('SERVICE_TOKEN'));
}

/** Llama al worker con la credencial de servicio. `body` puede ser FormData. */
export async function worker(
  ruta: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = env('SERVICE_TOKEN');
  if (!token) {
    // Mismo criterio que el worker: fallar cerrado y decir por qué.
    return new Response(
      JSON.stringify({ error: 'SERVICE_TOKEN sin configurar en el servidor web' }),
      { status: 503, headers: { 'content-type': 'application/json' } },
    );
  }
  return fetch(`${base()}${ruta}`, {
    ...init,
    headers: { ...(init.headers ?? {}), authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
}

/** La URL del worker, para las rutas públicas que no llevan credencial. */
export function urlPublica(ruta: string): string {
  return `${base()}${ruta}`;
}
