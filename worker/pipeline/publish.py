#!/usr/bin/env python3
"""
scene.json + viewer_template.html -> los dos entregables del visor.

  python3 publish.py <dir_trabajo> [dir_pipeline]

  viewer-web.html      ~31 KB · three.js desde CDN. Es el que se aloja.
  viewer-offline.html  ~620 KB · three.js incrustado. Abre sin red: es el que
                       se manda por correo o WhatsApp.

Sustituye a pack.py. La diferencia: el modelo va COMPRIMIDO (gzip -> base64) y
se descomprime en el navegador con DecompressionStream. En LM20 son 77 KB de
JSON que quedan en 5,3 KB, asi que el fichero alojado baja de 88 KB a 31 KB.

Coste: exige un navegador con DecompressionStream (Chrome 80+, Safari 16.4+,
Edge). Si falta, la pagina lo dice en vez de quedarse en blanco.
"""
import base64
import gzip
import json
import re
import sys
from pathlib import Path

CDN = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/'
       'three.min.js"></script>')

BOOT = """<script id="DZ" type="application/octet-stream">{b64}</script>
<script>
// El modelo va comprimido ({raw} B -> {gz} B) y se descomprime aqui antes de
// arrancar el visor. Un solo fichero, sin peticiones de datos.
window.__load = async function(){{
  const b = atob(document.getElementById('DZ').textContent.trim());
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  if (typeof DecompressionStream !== 'function') throw new Error('navegador sin DecompressionStream');
  const s = new Blob([u]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(new TextDecoder().decode(await new Response(s).arrayBuffer()));
}};
</script>
"""

TAIL = """<script>
window.__load().then(function(d){ window.SCENE_DATA = d; __app(); })
  .catch(function(e){
    document.body.innerHTML =
      '<div style="padding:28px;font:15px/1.5 -apple-system,sans-serif;color:#14161a">' +
      '<b>No se ha podido cargar el modelo.</b><br>' +
      'Abre el enlace en Chrome, Safari 16.4+ o Edge actualizados.<br>' +
      '<span style="color:#5b6270;font-size:13px">(' + e.message + ')</span></div>';
  });
</script>
</body>
</html>
"""


def build(work: Path, pipe: Path) -> dict:
    raw = json.dumps(json.loads((work / "scene.json").read_text(encoding="utf-8")),
                     separators=(",", ":"), ensure_ascii=False).encode()
    gz = gzip.compress(raw, 9)
    b64 = base64.b64encode(gz).decode()

    tpl = (pipe / "viewer_template.html").read_text(encoding="utf-8")
    lines = tpl.split("\n")

    # La linea de datos del template se sustituye entera por el bloque comprimido.
    i = next(n for n, l in enumerate(lines) if "__DATA__" in l)
    head, rest = "\n".join(lines[:i]), "\n".join(lines[i + 1:])

    # La IIFE pasa a funcion nombrada para poder arrancarla tras descomprimir.
    rest, n1 = re.subn(r"^\(function\(\)\{\n\"use strict\";",
                       "function __app(){\n\"use strict\";", rest, count=1, flags=re.M)
    rest, n2 = re.subn(r"^\}\)\(\);$", "}", rest, count=1, flags=re.M)
    if (n1, n2) != (1, 1):
        raise SystemExit(f"viewer_template.html no tiene la forma esperada ({n1},{n2})")

    rest = rest.replace("</body>\n</html>\n", "").rstrip() + "\n" + TAIL
    web = head + "\n" + BOOT.format(b64=b64, raw=len(raw), gz=len(gz)) + rest

    three = (pipe / "three.min.js").read_text(encoding="utf-8")
    offline = web.replace(CDN, "<script>" + three + "</script>")
    if offline == web:
        raise SystemExit("no encuentro la etiqueta del CDN de three.js en el template")

    (work / "viewer-web.html").write_text(web, encoding="utf-8")
    (work / "viewer-offline.html").write_text(offline, encoding="utf-8")
    return {"json_bytes": len(raw), "gzip_bytes": len(gz),
            "web_bytes": len(web.encode()), "offline_bytes": len(offline.encode())}


if __name__ == "__main__":
    work = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    pipe = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent
    r = build(work, pipe)
    print(f"viewer-web.html     {r['web_bytes']//1024} KB")
    print(f"viewer-offline.html {r['offline_bytes']//1024} KB")
    print(f"modelo {r['json_bytes']} B -> {r['gzip_bytes']} B comprimido")
