import { urlPublica } from '../../../../lib/worker';

// El visor autocontenido (~620 KB, three.js incrustado). Es el que se manda por
// correo o WhatsApp y el que abre sin red.
//
// Existe también porque el visor alojado depende de cdnjs para three.js: si la
// red del cliente bloquea ese CDN, este fichero es la salida. No es redundancia,
// es la única versión cuyo funcionamiento no depende de un tercero.
export async function GET(_: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!/^[a-f0-9]{8,64}$/.test(token)) return new Response('no existe', { status: 404 });
  const r = await fetch(urlPublica(`/p/${token}/offline`), { cache: 'no-store' });
  if (!r.ok) return new Response('no existe', { status: 404 });
  return new Response(await r.text(), {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'content-disposition': `inline; filename="reforma-${token.slice(0, 6)}.html"`,
      'x-robots-tag': 'noindex, nofollow',
    },
  });
}
