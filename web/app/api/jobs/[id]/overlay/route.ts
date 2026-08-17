import { worker } from '../../../../../lib/worker';

// La superposición se sirve por aquí para que el <iframe> la cargue sin que el
// navegador necesite la credencial del worker.
export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await worker(`/jobs/${encodeURIComponent(id)}/overlay`);
  if (!r.ok) return new Response('todavía no hay superposición', { status: r.status });
  return new Response(await r.text(), {
    status: 200,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}
