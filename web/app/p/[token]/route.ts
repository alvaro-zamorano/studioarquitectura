import { urlPublica } from '../../../lib/worker';

// El enlace del cliente final, servido desde el dominio de la app.
// NO lleva credencial: la autenticación es que el token de 16 hex no se adivina.
// Se proxea en vez de redirigir para que el cliente nunca vea la URL del worker.
export async function GET(_: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!/^[a-f0-9]{8,64}$/.test(token)) return new Response('no existe', { status: 404 });
  const r = await fetch(urlPublica(`/p/${token}/`), { cache: 'no-store' });
  if (!r.ok) return new Response('no existe', { status: 404 });
  return new Response(await r.text(), {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'x-robots-tag': 'noindex, nofollow',
    },
  });
}
