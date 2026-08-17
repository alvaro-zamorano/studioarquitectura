import { worker } from '../../../../../lib/worker';

// La puerta 7. Solo se llega aquí por una acción explícita de una persona que
// ha visto la superposición. No hay ninguna ruta que la salte.
export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await worker(`/jobs/${encodeURIComponent(id)}/approve`, { method: 'POST' });
  return new Response(await r.text(), {
    status: r.status,
    headers: { 'content-type': 'application/json' },
  });
}
