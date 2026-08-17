#!/usr/bin/env python3
"""
PUERTA 9 · cobertura de etiquetas.  DXF + model.json -> pasa / falla

  python3 verify_coverage.py plano.dxf model.json

Por que existe
--------------
Las ocho puertas anteriores comprueban que lo extraido es correcto. Ninguna
comprueba que este COMPLETO. Con el plano de Milimetro da igual, porque el
extractor lee sus convenciones; con el plano de otro estudio no:

    convencion                       antes de esta puerta
    0,78x1,25  escrito 0.78x1.25     vanos 12->2, salida 0, ocho puertas en verde
    PUERTA 72.5 escrito P-725        puertas 6->2, salida 0, ocho puertas en verde
    12,50 m2   escrito 12,50 m²      muere en alto (esto si estaba cubierto)

Los dos primeros son el fallo peligroso: el sistema devuelve un modelo plausible
al que le faltan la mayoria de los huecos, y la puerta 8 lo disimula inventando
pasos deducidos. Un entregable asi llega al cliente sin que nada chille.

Como funciona
-------------
No usa umbrales. Es una CONTABILIDAD exacta en dos direcciones:

  (a) todo texto que el extractor reconoce como carpinteria tiene que haber
      acabado siendo un vano del modelo. Igualdad exacta, no proporcion.
  (b) todo texto que TIENE PINTA de carpinteria o de superficie con otra
      convencion de escritura y NO lo ha reconocido el extractor se reporta y
      la puerta falla.

(b) es la que importa: no mide lo que sabemos leer, busca lo que no sabemos leer.
El patron ancho es deliberadamente mas permisivo que el estricto — cualquier par
de numeros separados por x, con coma o con punto, con o sin espacios.

Nada de esto se ajusta para que pase. Si un plano nuevo hace fallar la puerta,
la respuesta es ensenar al extractor esa convencion, nunca relajar el patron.
"""
import json
import re
import sys

import ezdxf

# --- lo que el extractor SI sabe leer (identicos a pipeline.py) --------------
ESTRICTO = {
    "ventana": re.compile(r"^(\d),(\d+)x(\d),(\d+)"),
    "puerta":  re.compile(r"^(PUERTA|CORREDERA)\s+([\d.]+)"),
}
SUP_ESTRICTO = re.compile(r"(\d+),(\d+)\s*m2")
# altura libre: el extractor tambien lee estos ('H. 2,43m'), y hay que
# inventariarlos o el patron ancho de superficie los da por huerfanos.
TECHO_ESTRICTO = re.compile(r"^\s*H\.?\s*\d")

# --- lo que TIENE PINTA de serlo, escrito de cualquier otra forma ------------
# dos numeros separados por x: cubre 0.78x1.25, 78 x 125, 0,78 X 1,25, 78x125...
ANCHO_HUECO = re.compile(r"\d+\s*[.,]?\s*\d*\s*[xX×]\s*\d+\s*[.,]?\s*\d*")
# palabra de carpinteria seguida de un numero en cualquier formato
ANCHO_PUERTA = re.compile(
    r"\b(PUERTA|PTA|P\.?|CORREDERA|CORRED|VENTANA|VENT|BALCONERA|HUECO)\b[\s\-_.:]*\d",
    re.IGNORECASE)
# superficie con cualquier grafia de la unidad: m2, m², m^2, mts2, m 2
ANCHO_SUP = re.compile(r"\d+\s*[.,]\s*\d+\s*m\s*(?:\^?2|²|ts?2)?\b", re.IGNORECASE)

# capas que son rotulacion del documento, no del edificio
CAPAS_DOC = {"CAJETIN", "12-CARTELA", "TEXTO CARATULA", "Defpoints"}


def textos(dxf):
    doc = ezdxf.readfile(dxf)
    out = []
    for e in doc.modelspace():
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        if e.dxf.layer in CAPAS_DOC:
            continue
        t = (e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text).strip()
        if t:
            out.append((t, e.dxf.layer))
    return out


def run(dxf, model):
    m = json.load(open(model, encoding="utf-8"))
    ts = textos(dxf)

    leidos = {"ventana": [], "puerta": []}
    for t, _ in ts:
        for k, p in ESTRICTO.items():
            if p.search(t):
                leidos[k].append(t)
                break
    sup_leidas = [t for t, _ in ts if SUP_ESTRICTO.search(t)]
    techos_leidos = [t for t, _ in ts if TECHO_ESTRICTO.search(t)]

    vanos = [o for isl in m["islands"] for o in isl["openings"]]
    v_mod = sum(1 for o in vanos if o["kind"] == "ventana")
    p_mod = sum(1 for o in vanos if o["kind"] == "puerta")
    estancias = sum(len(isl["rooms"]) for isl in m["islands"])
    con_cota = sum(1 for isl in m["islands"] for r in isl["rooms"]
                   if r["height_source"] == "dibujo")

    fallos = []

    # (a) contabilidad: cada etiqueta leida es un vano del modelo
    print(f"  etiquetas de ventana en el plano: {len(leidos['ventana']):3}   "
          f"ventanas en el modelo: {v_mod:3}")
    print(f"  etiquetas de puerta  en el plano: {len(leidos['puerta']):3}   "
          f"puertas  en el modelo: {p_mod:3}")
    print(f"  textos de superficie en el plano: {len(sup_leidas):3}   "
          f"estancias en el modelo: {estancias:3}")
    print(f"  cotas de altura libre en el plano: {len(techos_leidos):3}   "
          f"estancias con cota: {con_cota:3}")
    if len(leidos["ventana"]) != v_mod:
        fallos.append(f"{len(leidos['ventana'])} etiquetas de ventana pero {v_mod} en el modelo")
    if len(leidos["puerta"]) != p_mod:
        fallos.append(f"{len(leidos['puerta'])} etiquetas de puerta pero {p_mod} en el modelo")
    if len(sup_leidas) != estancias:
        fallos.append(f"{len(sup_leidas)} textos de superficie pero {estancias} estancias")
    if len(techos_leidos) != con_cota:
        fallos.append(f"{len(techos_leidos)} cotas de altura pero {con_cota} "
                      f"estancias con altura del dibujo")

    # (b) lo que parece carpinteria o superficie y no se ha sabido leer
    huerfanos = []
    for t, L in ts:
        if (any(p.search(t) for p in ESTRICTO.values())
                or SUP_ESTRICTO.search(t) or TECHO_ESTRICTO.search(t)):
            continue
        motivo = None
        if ANCHO_HUECO.search(t):
            motivo = "parece medida de hueco (dos numeros con x)"
        elif ANCHO_PUERTA.search(t):
            motivo = "parece etiqueta de carpinteria"
        elif ANCHO_SUP.search(t):
            motivo = "parece superficie con otra grafia de la unidad"
        if motivo:
            huerfanos.append((t, L, motivo))

    if huerfanos:
        print(f"\n  {len(huerfanos)} texto(s) con pinta de carpinteria que el extractor NO lee:")
        for t, L, motivo in huerfanos:
            print(f"     [{L}] {t!r}  <- {motivo}")
        fallos.append(f"{len(huerfanos)} etiquetas no reconocidas "
                      f"(el extractor no conoce esta convencion de escritura)")
    else:
        print("\n  ningun texto con pinta de carpinteria se ha quedado sin leer")

    if fallos:
        print("\nFALLA [9 cobertura de etiquetas]")
        for f in fallos:
            print(f"   - {f}")
        print("\n   El modelo puede ser correcto y estar INCOMPLETO. No se entrega.")
        print("   Arreglo: ensenar al extractor esta convencion. NO relajar la puerta.")
        return 1

    print("\nOK  [9 cobertura de etiquetas] toda etiqueta del plano esta en el modelo")
    print("TODAS LAS PUERTAS OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(run(sys.argv[1], sys.argv[2]))
