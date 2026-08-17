'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';

// Pantalla 1 de 4: subir. El fichero va a /api/jobs, que lo reenvía al worker
// con la credencial de servicio. El navegador no ve ese token nunca.

export default function Subir() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [dwg, setDwg] = useState<File | null>(null);
  const [pdf, setPdf] = useState<File | null>(null);
  const [sobre, setSobre] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');

  function coger(fs: FileList | null) {
    if (!fs) return;
    for (const f of Array.from(fs)) {
      const n = f.name.toLowerCase();
      if (n.endsWith('.dwg')) setDwg(f);
      else if (n.endsWith('.pdf')) setPdf(f);
    }
  }

  async function enviar() {
    if (!dwg) return;
    setEnviando(true);
    setError('');
    const fd = new FormData();
    fd.append('dwg', dwg);
    if (pdf) fd.append('pdf', pdf);
    const r = await fetch('/api/jobs', { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(d.detail ?? d.error ?? `el worker ha respondido ${r.status}`);
      setEnviando(false);
      return;
    }
    router.push(`/jobs/${d.id}`);
  }

  return (
    <main>
      <h1>Nuevo levantamiento</h1>
      <p className="sub">
        El DWG del estudio. El PDF es opcional y solo sirve para cotejar a mano si algo
        no cuadra.
      </p>

      <div
        className={'drop' + (sobre ? ' on' : '')}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setSobre(true); }}
        onDragLeave={() => setSobre(false)}
        onDrop={(e) => { e.preventDefault(); setSobre(false); coger(e.dataTransfer.files); }}
        style={{ marginTop: 18 }}
      >
        <input
          ref={input}
          type="file"
          accept=".dwg,.pdf"
          multiple
          onChange={(e) => coger(e.target.files)}
        />
        {dwg ? (
          <>
            <div style={{ fontWeight: 500 }}>{dwg.name}</div>
            <p className="sub">
              {(dwg.size / 1024 / 1024).toFixed(1)} MB
              {pdf ? ` · con ${pdf.name}` : ' · sin PDF'}
            </p>
          </>
        ) : (
          <>
            <div style={{ fontWeight: 500 }}>Arrastra el .dwg aquí</div>
            <p className="sub">o pulsa para elegirlo</p>
          </>
        )}
      </div>

      <div style={{ marginTop: 18, display: 'flex', gap: 10, alignItems: 'center' }}>
        <button onClick={enviar} disabled={!dwg || enviando}>
          {enviando ? 'Procesando…' : 'Procesar'}
        </button>
        {dwg && !enviando && (
          <button className="ghost" onClick={() => { setDwg(null); setPdf(null); }}>
            Quitar
          </button>
        )}
      </div>

      {error && <p className="err" style={{ marginTop: 12 }}>{error}</p>}

      <div className="card">
        <h2>Qué va a pasar</h2>
        <p>
          Nueve comprobaciones automáticas sobre el plano: superficies contra el cajetín,
          luz de cada hueco contra su etiqueta de carpintería, y que toda estancia quede
          accesible. Tarda unos tres segundos.
        </p>
        <p style={{ marginTop: 8 }}>
          Después se para y te pide mirar la superposición sobre el plano original. Ese
          paso no se automatiza y sin él no hay enlace para el cliente.
        </p>
      </div>
    </main>
  );
}
