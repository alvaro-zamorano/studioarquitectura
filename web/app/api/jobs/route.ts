import { worker } from '../../../lib/worker';

// El fichero se reenvía tal cual al worker. No se guarda ni se inspecciona aquí:
// esta app es la cara, el motor es el contenedor.
export async function POST(req: Request) {
  const form = await req.formData();
  const r = await worker('/jobs', { method: 'POST', body: form });
  return new Response(await r.text(), {
    status: r.status,
    headers: { 'content-type': 'application/json' },
  });
}
