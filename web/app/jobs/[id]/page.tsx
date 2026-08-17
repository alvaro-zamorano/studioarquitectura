'use client';

import { use, useEffect, useState } from 'react';

// Pantallas 2, 3 y 4 en una sola ruta, porque son tres momentos del MISMO
// trabajo y separarlas en URLs distintas obligaría a navegar hacia atrás para
// entender lo que estás aprobando.
//
//   2 · estado     los pasos y la salida íntegra de cada verificador
//   3 · revisar    la superposición y un botón            <- la puerta 7
//   4 · compartir  el enlace del cliente y el fichero offline

type Paso = { nombre: string; ok: boolean; segundos: number; error: string; salida: string };
type Trabajo = {
  id: string;
  status: string;
  error: string;
  pasos: Paso[];
  enlace?: string;
  offline?: string;
  siguiente?: { aviso: string };
};

const ETIQUETA: Record<string, string> = {
  ingest: 'DWG → DXF',
  extract: 'extracción',
  cobertura: 'puerta 9 · cobertura',
  verify2d: 'puertas 1-5 · 2D',
  build3d: 'volumetría 3D',
  verify3d: 'puertas 1-8 · 3D',
  publish: 'visor',
};

const EN_CURSO = ['recibido', 'ingest', 'extract', 'cobertura', 'verify2d', 'build3d',
                  'verify3d', 'publish'];

export default function Trabajo({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [t, setT] = useState<Trabajo | null>(null);
  const [aprobando, setAprobando] = useState(false);
  const [fallo, setFallo] = useState('');

  useEffect(() => {
    let vivo = true;
    async function tick() {
      const r = await fetch(`/api/jobs/${id}`);
      if (!r.ok) { setFallo(`el worker ha respondido ${r.status}`); return; }
      const d: Trabajo = await r.json();
      if (!vivo) return;
      setT(d);
      if (EN_CURSO.includes(d.status)) setTimeout(tick, 900);
    }
    tick();
    return () => { vivo = false; };
  }, [id]);

  async function aprobar() {
    setAprobando(true);
    const r = await fetch(`/api/jobs/${id}/approve`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { setFallo(d.detail ?? `el worker ha respondido ${r.status}`); setAprobando(false); return; }
    setT((v) => (v ? { ...v, status: d.status, enlace: d.enlace, offline: d.offline } : v));
    setAprobando(false);
  }

  if (fallo) return <main><h1>Error</h1><p className="err">{fallo}</p></main>;
  if (!t) return <main><p>Cargando…</p></main>;

  const enCurso = EN_CURSO.includes(t.status);
  const revisar = t.status === 'revision_humana';
  const publicado = t.status === 'publicado';
  // Los dos enlaces se pintan absolutos: son para copiar y pegar en un correo.
  const origen = typeof window !== 'undefined' ? window.location.origin : '';

  return (
    <main>
      <h1>
        {enCurso && 'Procesando'}
        {revisar && 'Falta que lo mires'}
        {publicado && 'Publicado'}
        {t.status === 'fallo' && 'El plano no ha pasado las puertas'}
      </h1>
      <p className="sub" style={{ fontFamily: 'ui-monospace, monospace' }}>{t.id}</p>

      {/* ── 2 · estado ─────────────────────────────────────────────── */}
      <div className="card">
        <h2>Comprobaciones</h2>
        {t.pasos.map((p) => (
          <div key={p.nombre} className="envoltura-paso">
            <div className={'paso' + (p.salida || !p.ok ? ' con-detalle' : '')}>
              <div className={'dot ' + (p.ok ? 'ok' : 'no')} />
              <div className="n">{ETIQUETA[p.nombre] ?? p.nombre}</div>
              <div className="t">{p.segundos.toFixed(2)} s</div>
            </div>
            {(!p.ok || p.salida) && (
              <details>
                <summary>{p.ok ? 'ver la salida del verificador' : `falla: ${p.error}`}</summary>
                <pre>{p.salida || '(sin salida)'}</pre>
              </details>
            )}
          </div>
        ))}
        {enCurso && (
          <div className="paso">
            <div className="dot wait" />
            <div className="n" style={{ color: 'var(--ink-2)' }}>en curso…</div>
          </div>
        )}
      </div>

      {t.status === 'fallo' && (
        <div className="card">
          <h2>Qué hacer</h2>
          <p>
            El fallo está en la salida del paso en rojo, arriba. Si es la puerta 9, el
            informe nombra las etiquetas del plano que el extractor no sabe leer: hay que
            enseñarle esa convención. <b>No se relaja la comprobación.</b>
          </p>
        </div>
      )}

      {/* ── 3 · revisar · LA PUERTA 7 ──────────────────────────────── */}
      {revisar && (
        <div className="card">
          <h2>Superposición sobre el plano original</h2>
          <div className="aviso">
            Las nueve comprobaciones de máquina están en verde. Queda la única que no se
            puede automatizar: <b>que cada estancia coloreada encaje dentro de las líneas
            negras de muro.</b> Si un color se sale o invade la de al lado, la extracción
            es numéricamente correcta y geométricamente falsa — y ninguna máquina lo
            detecta.
          </div>
          <p style={{ marginTop: 10, fontSize: 13 }}>
            Trae <b>las dos plantas apiladas</b> — estado actual y reformado. Desplázate
            dentro del marco para ver la segunda.
          </p>
          <iframe src={`/api/jobs/${id}/overlay`} title="superposición" style={{ marginTop: 8 }} />
          <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
            <button onClick={aprobar} disabled={aprobando}>
              {aprobando ? 'Publicando…' : 'Encaja: generar el enlace'}
            </button>
            <a href={`/api/jobs/${id}/overlay`} target="_blank" rel="noreferrer"
               style={{ fontSize: 13.5 }}>
              abrir a pantalla completa
            </a>
          </div>
        </div>
      )}

      {/* ── 4 · compartir ──────────────────────────────────────────── */}
      {publicado && t.enlace && (
        <div className="card">
          <h2>Para el cliente final</h2>
          <p>Abre en el móvil. No hace falta cuenta ni instalar nada.</p>
          <a className="enlace" href={t.enlace} target="_blank" rel="noreferrer">
            {origen}{t.enlace}
          </a>
          <p style={{ marginTop: 14 }}>
            Para correo o WhatsApp, la versión que abre sin red:
          </p>
          <a className="enlace" href={t.offline} target="_blank" rel="noreferrer">
            {origen}{t.offline}
          </a>
          <p style={{ marginTop: 14, fontSize: 13 }}>
            El enlace no se indexa y no se adivina, pero es público para quien lo tenga.
            Trátalo como el propio plano.
          </p>
        </div>
      )}
    </main>
  );
}
