#!/usr/bin/env python3
"""
Plano CAD -> modelo verificado.  Estado: etapas 1-3 cerradas y verificadas.

  python pipeline.py ingest  entrada.dwg  plano.dxf
  python pipeline.py extract plano.dxf    model.json
  python pipeline.py verify  model.json   plano.dxf  overlay.html

Ver HANDOFF-plano-3d.md.  Reglas que no se tocan:
  - Nunca leer $INSUNITS: se autodetecta por magnitud.
  - Nunca mapear capas por nombre: se detectan por forma.
  - Ningun parametro se ajusta contra la metrica de validacion.
  - No se pasa a 3D sin que un humano haya mirado la superposicion.
"""
import sys, os, re, json, math, subprocess, itertools
import ezdxf
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union


# ---------------------------------------------------------------- 1. INGEST
def ingest(dwg, dxf):
    exe = next((p for p in ("dwg2dxf", "/usr/local/bin/dwg2dxf",
                            "/opt/homebrew/bin/dwg2dxf") if _which(p)), None)
    if not exe:
        sys.exit("falta dwg2dxf (brew install libredwg)")
    subprocess.run([exe, "-y", "-o", dxf, dwg], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"ok  {dwg} -> {dxf}")


def _which(p):
    from shutil import which
    return which(p) or (os.path.exists(p) and os.access(p, os.X_OK))


# ------------------------------------------------- utilidades de lectura
def _polys(msp, layer):
    out = []
    for e in msp:
        if e.dxf.layer != layer or e.dxftype() != "LWPOLYLINE":
            continue
        p = [(q[0], q[1]) for q in e.get_points("xy")]
        if len(p) < 3:
            continue
        g = Polygon(p)
        if not g.is_valid:
            g = g.buffer(0)
        if g.geom_type == "Polygon" and g.area > 1e-4:
            out.append(g)
    return out


def _texts(msp, layer=None):
    out = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        if layer and e.dxf.layer != layer:
            continue
        t = (e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text).strip()
        if t:
            out.append((t, Point(e.dxf.insert[0], e.dxf.insert[1]), e.dxf.layer))
    return out


def detect_scale(msp):
    """TRAMPA 3.1 - $INSUNITS miente.  Magnitud de la envolvente."""
    xs, ys = [], []
    for e in msp:
        if e.dxftype() != "LWPOLYLINE":
            continue
        for q in e.get_points("xy"):
            xs.append(q[0]); ys.append(q[1])
    if not xs:
        return 1.0, "sin geometria"
    d = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    for f, lo, hi, name in ((1.0, 5, 400, "metros"), (0.01, 500, 40000, "centimetros"),
                            (0.001, 5000, 400000, "milimetros")):
        if lo < d < hi:
            return f, f"{name} (diagonal {d:.1f} u, cabecera dice {msp.doc.header.get('$INSUNITS')})"
    return 1.0, f"indeterminado (diagonal {d:.1f})"


def detect_rooms_layer(msp):
    """TRAMPA 3.3 - los nombres no significan nada.  Se busca la capa cuyas
    polilineas cerradas tienen areas que coinciden con los textos SUP. x,xx m2."""
    decl = []
    for t, p, _ in _texts(msp):
        m = re.search(r"(\d+),(\d+)\s*m2", t)
        if m:
            decl.append((float(f"{m.group(1)}.{m.group(2)}"), p))
    if not decl:
        sys.exit("no hay textos de superficie: no se puede detectar la capa de estancias")
    layers = {e.dxf.layer for e in msp if e.dxftype() == "LWPOLYLINE"}
    best = None
    for L in layers:
        gs = _polys(msp, L)
        hits = sum(1 for g in gs for a, p in decl
                   if g.contains(p) and abs(g.area - a) < 0.02)
        if hits and (best is None or hits > best[0]):
            best = (hits, L)
    if not best:
        sys.exit("ninguna capa cuadra con las superficies declaradas")
    print(f"    capa de estancias detectada por forma: {best[1]!r} ({best[0]}/{len(decl)} coinciden)")
    return best[1], decl


def detect_walls_layer(msp, rooms):
    """Mayor area de poligonos cerrados que NO se solapa con las estancias."""
    UR = unary_union(rooms)
    best = None
    for L in {e.dxf.layer for e in msp if e.dxftype() == "LWPOLYLINE"}:
        gs = _polys(msp, L)
        if not gs:
            continue
        U = unary_union(gs)
        if U.area < 0.5 or U.intersection(UR).area > 0.05 * U.area:
            continue
        if best is None or U.area > best[0]:
            best = (U.area, L)
    print(f"    capa de muros detectada por forma: {best[1]!r} ({best[0]:.2f} m2)")
    return best[1]


def split_islands(gs, gap=2.0):
    """TRAMPA 3.2 - varias plantas en el mismo modelspace."""
    ys = sorted(g.centroid.y for g in gs)
    cuts = [(ys[i] + ys[i + 1]) / 2 for i in range(len(ys) - 1)
            if ys[i + 1] - ys[i] > gap]
    bands = [-math.inf] + cuts + [math.inf]
    return [[g for g in gs if bands[i] <= g.centroid.y < bands[i + 1]]
            for i in range(len(bands) - 1)]


# --------------------------------------------------------------- 2. EXTRACT
def extract(dxf, out):
    doc = ezdxf.readfile(dxf); msp = doc.modelspace()
    S, why = detect_scale(msp)
    print(f"    escala: x{S}  ({why})")
    RL, decl = detect_rooms_layer(msp)
    rooms_all = _polys(msp, RL)
    WL = detect_walls_layer(msp, rooms_all)
    walls_all = _polys(msp, WL)

    # El nombre de la estancia es el texto que acompaña a su texto de superficie
    # (se dibujan como par, nombre encima). Emparejar por proximidad, no por capa.
    cands = [(t, p) for t, p, L in _texts(msp)
             if re.search(r"[A-ZÁÉÍÓÚÑ]{3,}", t) and not re.search(r"m2|SUP\.", t)]
    names = []
    for a, ap in decl:
        near = [(math.hypot(p.x - ap.x, p.y - ap.y), t, p) for t, p in cands
                if abs(p.x - ap.x) < 3 and 0 < p.y - ap.y < 1.5]
        if near:
            near.sort()
            names.append((near[0][1], near[0][2]))
    ceil = [(t, p) for t, p, L in _texts(msp) if re.match(r"\s*H\.?\s*\d", t)]
    carp = [(t, p) for t, p, L in _texts(msp)
            if re.match(r"(\d,\d+x\d,\d+|PUERTA|CORREDERA)", t)]

    islands = split_islands(rooms_all)
    data = {"source": os.path.basename(dxf), "scale": S, "units": "m",
            "layers": {"rooms": RL, "walls": WL}, "islands": []}
    for k, rg in enumerate(islands):
        if not rg:
            continue
        bb = unary_union(rg).bounds
        inside = lambda p: bb[0] - 3 < p.x < bb[2] + 3 and bb[1] - 3 < p.y < bb[3] + 3
        rw = [g for g in walls_all if inside(g.centroid)]
        rr = []
        for g in rg:
            nm = [t for t, p in names if g.contains(p)]
            ar = [a for a, p in decl if g.contains(p)]
            hh = [t for t, p in ceil if g.contains(p)]
            h = None
            if hh:
                m = re.search(r"(\d+),(\d+)", hh[0])
                if m:
                    h = float(f"{m.group(1)}.{m.group(2)}")
            rr.append({"name": nm[0] if nm else "(sin etiqueta)",
                       "area_decl": ar[0] if ar else None,
                       "area_calc": round(g.area * S * S, 3),
                       "height": h, "height_source": "dibujo" if h else "asumida",
                       "poly": [[round(x * S, 4), round(y * S, 4)] for x, y in g.exterior.coords]})
        ops = []
        for t, p in carp:
            if not inside(p):
                continue
            m = re.match(r"(\d),(\d+)x(\d),(\d+)", t)
            if m:
                ops.append({"kind": "ventana", "label": t,
                            "width": float(f"{m.group(1)}.{m.group(2)}"),
                            "height": float(f"{m.group(3)}.{m.group(4)}"),
                            "x": round(p.x * S, 4), "y": round(p.y * S, 4)})
            else:
                m = re.match(r"(PUERTA|CORREDERA)\s+([\d.]+)", t)
                if m:
                    ops.append({"kind": "puerta", "label": t,
                                "width": float(m.group(2)) / 100, "height": 2.10,
                                "x": round(p.x * S, 4), "y": round(p.y * S, 4)})
        HS = [r["height"] for r in rr if r["height"]]
        data["islands"].append({
            "id": k, "bbox": [round(v * S, 3) for v in bb],
            "height_max": max(HS) if HS else 2.72, "height_assumed": not HS,
            "rooms": rr, "openings": ops,
            "walls": [{"poly": [[round(x * S, 4), round(y * S, 4)] for x, y in g.exterior.coords],
                       "holes": [[[round(x * S, 4), round(y * S, 4)] for x, y in i.coords]
                                 for i in g.interiors]} for g in rw]})
        print(f"    isla {k}: {len(rr)} estancias, {len(rw)} muros, {len(ops)} vanos")
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"ok  -> {out}")


# ---------------------------------------------------------------- 3. VERIFY
def verify(model, dxf, html):
    d = json.load(open(model))
    doc = ezdxf.readfile(dxf); msp = doc.modelspace(); S = d["scale"]
    dims = []
    for e in msp:
        if e.dxftype() == "DIMENSION":
            try:
                m = e.get_measurement()
                if isinstance(m, (int, float)) and m > 0:
                    dims.append(round(float(m) * S, 3))
            except Exception:
                pass
    allok = True
    for isl in d["islands"]:
        P = [Polygon(r["poly"]) for r in isl["rooms"]]
        W = [Polygon(w["poly"], w["holes"]) for w in isl["walls"]]
        print(f"\n--- isla {isl['id']} ---")
        # Las aristas compartidas producen slivers degenerados de anchura ~0.
        # Solo cuenta el solape con extension 2D real (se erosiona 1 mm).
        def _ov(x, y):
            i = x.intersection(y)
            return 0.0 if i.is_empty else max(i.buffer(-0.001).area, 0.0)
        g1 = max((_ov(P[a], P[b]) for a, b in itertools.combinations(range(len(P)), 2)), default=0)
        g2 = sum(1 for p in P if p.is_valid and p.exterior.is_ring)
        g3 = unary_union(P).intersection(unary_union(W)).area if W else 0
        errs = [abs(r["area_calc"] - r["area_decl"]) for r in isl["rooms"] if r["area_decl"]]
        g4 = max(errs) if errs else None
        ok = 0; tot = 0
        for r, p in zip(isl["rooms"], P):
            mr = p.minimum_rotated_rectangle
            xs, ys = mr.exterior.coords.xy
            L = sorted(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])) for i in range(4))
            for v in (L[0], L[3]):
                tot += 1
                if dims and min(abs(v - c) for c in dims) < 0.05:
                    ok += 1
        chk = [("[1] solape entre estancias", f"{g1*1e4:.2f} cm2", g1 < 1e-4),
               ("[2] poligonos validos", f"{g2}/{len(P)}", g2 == len(P)),
               ("[3] solape estancias/muros", f"{g3*1e4:.1f} cm2", g3 < 0.02),
               ("[4] area calc vs declarada", f"max {g4*1e4:.1f} cm2" if g4 else "n/d", g4 is not None and g4 < 0.02),
               ("[5] lados vs cotas DIMENSION", f"{ok}/{tot}", tot and ok / tot > 0.85)]
        for n, v, p in chk:
            print(f"  {'OK  ' if p else 'FALLA'} {n:32} {v}")
            allok &= p
    _overlay(d, dxf, html)
    print(f"\n{'TODAS LAS PUERTAS OK' if allok else 'HAY PUERTAS EN FALLO'}")
    print(f"superposicion -> {html}")
    print("PUERTA 7: un humano debe mirarla antes de pasar a 3D.")
    return allok


def _overlay(d, dxf, html):
    doc = ezdxf.readfile(dxf); msp = doc.modelspace(); S = d["scale"]
    seg = []
    for e in msp:
        if e.dxf.layer in ("CAJETIN", "12-CARTELA", "TEXTO CARATULA", "Defpoints"):
            continue
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE":
                p = [(q[0] * S, q[1] * S) for q in e.get_points("xy")]
                if e.closed and len(p) > 2:
                    p += [p[0]]
                seg += [(p[i], p[i + 1], e.dxf.layer) for i in range(len(p) - 1)]
            elif t == "LINE":
                seg.append(((e.dxf.start.x * S, e.dxf.start.y * S),
                            (e.dxf.end.x * S, e.dxf.end.y * S), e.dxf.layer))
            elif t in ("ARC", "CIRCLE"):
                a0, a1 = (math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)) \
                    if t == "ARC" else (0, 2 * math.pi)
                if a1 < a0:
                    a1 += 2 * math.pi
                pts = [(e.dxf.center.x * S + e.dxf.radius * S * math.cos(a0 + (a1 - a0) * i / 20),
                        e.dxf.center.y * S + e.dxf.radius * S * math.sin(a0 + (a1 - a0) * i / 20))
                       for i in range(21)]
                seg += [(pts[i], pts[i + 1], e.dxf.layer) for i in range(20)]
        except Exception:
            pass
    xs = [p[i][0] for p in seg for i in (0, 1)]; ys = [p[i][1] for p in seg for i in (0, 1)]
    X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
    K = 1400 / (X1 - X0)
    fx = lambda x: (x - X0) * K
    fy = lambda y: (Y1 - y) * K
    W = d["layers"]["walls"]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {(X1-X0)*K:.0f} {(Y1-Y0)*K:.0f}" style="background:#fff">']
    for a, b, L in seg:
        if L == d["layers"]["rooms"]:
            continue
        c, w = ("#111", 1.6) if L == W else ("#B9BCC2", 0.9)
        o.append(f'<line x1="{fx(a[0]):.1f}" y1="{fy(a[1]):.1f}" x2="{fx(b[0]):.1f}" y2="{fy(b[1]):.1f}" stroke="{c}" stroke-width="{w}"/>')
    COL = ["#2F6BE0", "#17A398", "#E2761B", "#B3439B", "#3FA34D", "#D64545", "#7A5AF8", "#0E7490"]
    for isl in d["islands"]:
        for i, r in enumerate(isl["rooms"]):
            c = COL[i % len(COL)]
            pts = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in r["poly"])
            P = Polygon(r["poly"]); rp = P.representative_point()
            o.append(f'<polygon points="{pts}" fill="{c}" fill-opacity=".22" stroke="{c}" stroke-width="2.2"/>')
            o.append(f'<text x="{fx(rp.x):.1f}" y="{fy(rp.y):.1f}" font-family="monospace" font-size="13" font-weight="600" fill="{c}" text-anchor="middle">{r["name"]}</text>')
            dv = f'{r["area_decl"]:.2f}' if r["area_decl"] else "?"
            o.append(f'<text x="{fx(rp.x):.1f}" y="{fy(rp.y)+15:.1f}" font-family="monospace" font-size="11" fill="{c}" text-anchor="middle">{r["area_calc"]:.2f} / {dv} m²</text>')
    o.append("</svg>")
    open(html, "w").write(
        '<!DOCTYPE html><meta charset=utf-8><body style="margin:0;background:#E9E9E4;'
        'font-family:system-ui"><div style="max-width:1180px;margin:auto;padding:20px">'
        '<h1 style="font-size:15px">Superposición de verificación</h1>'
        '<p style="font-size:13px;max-width:64ch;color:#33363B">Cada estancia coloreada debe '
        'encajar dentro de las líneas negras de muro. Si un color se sale o invade la estancia '
        'contigua, la extracción está mal y no se pasa a 3D.</p>'
        '<div style="border:1px solid #CFCFC8;background:#fff;padding:8px">'
        + "".join(o).replace("<svg", '<svg style="width:100%;height:auto;display:block"', 1)
        + "</div></div></body>")


# --------------------------------------------------------------------- CLI
if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    {"ingest": ingest, "extract": extract, "verify": verify}[cmd](*args)
