#!/usr/bin/env python3
"""
model.json -> scene.json   (etapa 4: volumetria 3D)

Metodo
------
1. Las estancias son la fuente verificada (15/15 exactas contra `SUP. x,xx m2`).
   La masa de muro se SINTETIZA como  envolvente - estancias.  Asi la particion
   interior sale del mismo dato ya verificado y no de una capa que en este DWG
   no la contiene.
2. Los vanos se localizan por rayo sobre la geometria de '01-SECC' y se validan
   contra la anchura de la ETIQUETA DE TEXTO -- fuente independiente (HANDOFF
   6.6). Tolerancia 5 cm, fija. Lo que no valida se reporta, no se ajusta.
3. El solido se corta en franjas horizontales por las cotas criticas (0, alfeizar,
   dintel, techo) y en cada franja se restan en 2D los vanos activos. CSG en 2D,
   exacto y barato: no hay booleanas 3D.

Antepechos y dinteles salen solos de este metodo: la franja 0-1,00 conserva el
muro bajo la ventana; la franja dintel-techo lo conserva encima.
"""
import json, sys, math
from shapely.geometry import Polygon, box, LineString, Point as ShPoint
from shapely.ops import unary_union, nearest_points
from openings import locate

SRC = sys.argv[1] if len(sys.argv) > 1 else "model-LM20.json"
DST = sys.argv[2] if len(sys.argv) > 2 else "scene.json"

SILL_WINDOW = 1.00      # HANDOFF §4: "h antepecho = 1,00" x5. Declarado, no inventado.
VARIANT = {0: {"key": "reformado", "label": "Estado reformado"},
           1: {"key": "actual", "label": "Estado actual"}}

m = json.load(open(SRC))
out_islands = []
report = []


def ring(p, x0, y0):
    return [[round(x - x0, 4), round(y - y0, 4)] for x, y in p]


def poly_out(g, x0, y0):
    return {"shell": ring(g.exterior.coords, x0, y0),
            "holes": [ring(i.coords, x0, y0) for i in g.interiors]}


def explode(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [q for q in g.geoms if q.geom_type == "Polygon" and q.area > 1e-6]


for isl in m["islands"]:
    x0, y0, x1, y1 = isl["bbox"]
    iid = isl["id"]
    v = VARIANT.get(iid, {"key": f"isla{iid}", "label": f"Isla {iid}"})

    rooms_g = []
    for r in isl["rooms"]:
        g = Polygon(r["poly"])
        if not g.is_valid:
            g = g.buffer(0)
        rooms_g.append(g)
    R = unary_union(rooms_g)

    walls_g = []
    for w in isl["walls"]:
        g = Polygon(w["poly"], w.get("holes") or [])
        if not g.is_valid:
            g = g.buffer(0)
        walls_g.append(g)
    UW = unary_union(walls_g)

    # --- envolvente
    # La union de estancias + muros de seccion sale TROCEADA: las particiones
    # interiores no estan dibujadas en '01-SECC', asi que entre dos estancias hay
    # aire, no material. Se cierra morfologicamente con un radio DERIVADO de los
    # propios huecos entre estancias contiguas (no un valor elegido a ojo), y
    # despues se rellenan los interiores. La masa de muro es el negativo.
    gaps = []
    for a in range(len(rooms_g)):
        for b in range(a + 1, len(rooms_g)):
            d = rooms_g[a].distance(rooms_g[b])
            if 1e-9 < d <= 0.60:
                gaps.append(d)
    g = (max(gaps) / 2 + 0.01) if gaps else 0.06
    env = unary_union([R, UW])
    env = env.buffer(g, join_style=2, mitre_limit=8).buffer(-g, join_style=2, mitre_limit=8)
    env = unary_union([Polygon(p.exterior) for p in explode(env)])
    mass = env.difference(R.buffer(0.0005))       # masa de muro (incluye particiones)

    H = isl["height_max"]

    # ---------------- vanos ----------------
    ops = []
    for o in isl["openings"]:
        is_win = o["kind"].startswith("vent")
        loc = locate(UW, o["x"], o["y"], o["width"])
        rec = {"kind": o["kind"], "label": o["label"],
               "span": o["width"], "h": o["height"]}
        if loc:
            rec.update(axis=loc["axis"], start=round(loc["start"] - (x0 if loc["axis"] == 0 else y0), 4),
                       end=round(loc["end"] - (x0 if loc["axis"] == 0 else y0), 4),
                       perp=round(loc["perp_center"] - (y0 if loc["axis"] == 0 else x0), 4),
                       thickness=round(loc["thickness"], 4),
                       status="verificado", err_mm=round(loc["err"] * 1000, 1))
        else:
            # posicion no verificable con la geometria disponible -> se marca
            rec.update(axis=None, status="no_localizado",
                       x=round(o["x"] - x0, 4), y=round(o["y"] - y0, 4))
        # una "ventana" de 2,10 de alto es una balconera: no lleva antepecho
        rec["sill"] = SILL_WINDOW if (is_win and o["height"] < 2.0) else 0.0
        rec["head"] = min(rec["sill"] + o["height"], H)
        ops.append(rec)

    # --- puertas interiores: '01-SECC' no contiene las particiones de este DWG,
    #     asi que su luz no es medible. Se apoyan sobre la masa sintetizada y se
    #     marcan como aproximadas (+-10 cm a lo largo del muro). NO se calibra
    #     ningun offset contra las ventanas: seria ajustar contra la validacion.
    for o, src in zip(ops, isl["openings"]):
        if o["status"] != "no_localizado":
            continue
        p = ShPoint(src["x"], src["y"])
        # una puerta interior se apoya en un muro que SEPARA DOS ESTANCIAS.
        # Se busca cruzando el punto con dos rectas y quedandose con la banda de
        # muro mas cercana que cumpla: espesor de tabique y estancia a ambos lados.
        best = None
        for a in (0, 1):
            ln = (LineString([(p.x, p.y - 1.6), (p.x, p.y + 1.6)]) if a == 0
                  else LineString([(p.x - 1.6, p.y), (p.x + 1.6, p.y)]))
            it = ln.intersection(mass)
            if it.is_empty:
                continue
            segs = [it] if it.geom_type == "LineString" else [g for g in it.geoms
                                                              if g.geom_type == "LineString"]
            for s in segs:
                if not (0.04 <= s.length <= 0.60):
                    continue
                b = s.bounds
                lo, hi = (b[1], b[3]) if a == 0 else (b[0], b[2])
                s1 = ShPoint(p.x, lo - 0.06) if a == 0 else ShPoint(lo - 0.06, p.y)
                s2 = ShPoint(p.x, hi + 0.06) if a == 0 else ShPoint(hi + 0.06, p.y)
                if not (R.contains(s1) and R.contains(s2)):
                    continue                    # da a fachada: no es tabique interior
                d = s.distance(p)
                if best is None or d < best[0]:
                    best = (d, a, s.length, (lo + hi) / 2)
        if best is None:
            continue                             # se queda como 'no_localizado'
        _, ax, th, perp = best
        c = src["x"] if ax == 0 else src["y"]
        o.update(axis=ax, thickness=round(th, 4), status="aproximado",
                 start=round(c - src["width"] / 2 - (x0 if ax == 0 else y0), 4),
                 end=round(c + src["width"] / 2 - (x0 if ax == 0 else y0), 4),
                 perp=round(perp - (y0 if ax == 0 else x0), 4))

    # --- conectividad: ninguna estancia puede quedar sin acceso -----------------
    # El plano del reformado solo etiqueta 2 puertas para 7 estancias, asi que
    # tres quedarian tapiadas. Se infiere un paso de 0,725 (el ancho de puerta que
    # el propio plano usa) centrado en el pano mas largo que comparten, y se marca
    # 'inferido': no esta medido, esta deducido de que la estancia tiene que ser
    # accesible. Nunca se infiere un hueco de fachada.
    def facing_edge(A, B):
        """arista mas larga de A que mira DE VERDAD a B.
        No basta con que la arista este a la distancia justa: se cruza el muro
        perpendicularmente desde su punto medio y se exige aterrizar dentro de B.
        Sin esta comprobacion, una arista que da a una tercera estancia situada a
        la misma distancia se cuela y el paso acaba en el sitio equivocado."""
        d = A.distance(B)
        best = None
        cs = list(A.exterior.coords)
        for p, q in zip(cs, cs[1:]):
            seg = LineString([p, q])
            if seg.length < 0.30 or seg.distance(B) > d + 0.006:
                continue
            (px, py), (qx, qy) = list(seg.coords)[:2]
            L = math.hypot(qx - px, qy - py)
            nx, ny = -(qy - py) / L, (qx - px) / L
            mx, my = (px + qx) / 2, (py + qy) / 2
            sign = 0
            for s in (1, -1):
                if B.contains(ShPoint(mx + nx * s * (d + 0.03), my + ny * s * (d + 0.03))):
                    sign = s
                    break
            if sign == 0:
                continue
            if best is None or seg.length > best[0].length:
                best = (seg, sign)
        return (best[0], d, best[1]) if best else (None, d, 0)

    def link(i, j):
        A, B = rooms_g[i], rooms_g[j]
        seg, d, sign = facing_edge(A, B)
        if seg is None or not (0.03 <= d <= 0.45):
            return None
        (px, py), (qx, qy) = list(seg.coords)[:2]
        axis = 0 if abs(qx - px) >= abs(qy - py) else 1
        lo, hi = (min(px, qx), max(px, qx)) if axis == 0 else (min(py, qy), max(py, qy))
        span = min(0.725, (hi - lo) - 0.10)
        if span < 0.60:
            return None
        c = (lo + hi) / 2
        edge_perp = py if axis == 0 else px
        L = math.hypot(qx - px, qy - py)
        npx, npy = -(qy - py) / L, (qx - px) / L
        perp = edge_perp + sign * (npy if axis == 0 else npx) * d / 2
        return {"kind": "puerta", "label": "paso inferido", "span": round(span, 3),
                "h": 2.10, "sill": 0.0, "head": min(2.10, H), "axis": axis,
                "thickness": round(d, 4), "start": round(c - span/2 - x0f(axis), 4),
                "end": round(c + span/2 - x0f(axis), 4),
                "perp": round(perp - y0f(axis), 4), "status": "inferido",
                "rooms": [isl["rooms"][i]["name"], isl["rooms"][j]["name"]]}

    def x0f(axis):
        return x0 if axis == 0 else y0

    def y0f(axis):
        return y0 if axis == 0 else x0

    placed = [o for o in ops if o["status"] in ("verificado", "aproximado")]

    # grafo: arista si las estancias se tocan (paso libre) o si un hueco las une
    n = len(rooms_g)
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    for a in range(n):
        for b in range(a + 1, n):
            if rooms_g[a].distance(rooms_g[b]) < 1e-6:
                union(a, b)
    def sides_of(o):
        """estancias a un lado y otro del hueco, tomadas cruzando el muro.
        Una VENTANA no comunica dos estancias: solo cuentan las puertas."""
        c = (o["start"] + o["end"]) / 2
        t = o["thickness"] / 2 + 0.06
        out = []
        for s in (-1, 1):
            px = c + x0 if o["axis"] == 0 else o["perp"] + x0 + s * t
            py = o["perp"] + y0 + s * t if o["axis"] == 0 else c + y0
            p = ShPoint(px, py)
            hit = [k for k in range(n) if rooms_g[k].contains(p)]
            out.append(hit[0] if hit else None)
        return out

    def is_passage(o):
        """cualquier hueco que arranque en el suelo comunica dos espacios:
        una balconera es una puerta aunque el plano la etiquete como ventana"""
        return o["kind"] == "puerta" or o["sill"] <= 0.01

    for o in placed:
        if not is_passage(o):
            continue
        a, b = sides_of(o)
        o["rooms"] = [isl["rooms"][k]["name"] if k is not None else "exterior" for k in (a, b)]
        if a is not None and b is not None:
            union(a, b)

    guard = 0
    while len({find(k) for k in range(n)}) > 1 and guard < n:
        guard += 1
        comps = {}
        for k in range(n):
            comps.setdefault(find(k), []).append(k)
        big = max(comps.values(), key=lambda c: sum(rooms_g[k].area for k in c))
        rest = [k for k in range(n) if k not in big]
        cand = []
        for i in rest:
            for j in big:
                seg, d, _sg = facing_edge(rooms_g[i], rooms_g[j])
                if seg is not None:
                    cand.append((seg.length, i, j))
        if not cand:
            break
        # se comunica preferentemente contra una estancia de circulacion: un bano
        # o un dormitorio se abren al pasillo, no a la cocina. Es una regla de
        # oficio, no una medida, y por eso el hueco queda marcado 'inferido'.
        CIRC = ("HALL", "PASILLO", "DISTRIBUIDOR", "RECIBIDOR", "VESTIBULO", "VESTÍBULO")
        def rank(t):
            L, i, j = t
            nm = isl["rooms"][j]["name"].upper()
            return (1 if any(c in nm for c in CIRC) else 0, L)
        cand.sort(key=rank, reverse=True)
        made = False
        for _, i, j in cand:
            o = link(i, j)
            if o:
                ops.append(o); placed.append(o); union(i, j); made = True
                break
        if not made:
            break

    def op_rect(o, pad=0.30):
        """rectangulo del vano, engordado en perpendicular para atravesar el muro"""
        if o["axis"] == 0:
            return box(o["start"], o["perp"] - pad, o["end"], o["perp"] + pad)
        return box(o["perp"] - pad, o["start"], o["perp"] + pad, o["end"])

    def op_fill(o):
        """rectangulo del hueco RELLENO al espesor del muro: devuelve al solido el
        material que la seccion a 1,20 m no dibuja. Es el paso que convierte
        'muro con hueco' en 'muro macizo' antes de restar el vano real por franjas.
        Sin esto no hay antepecho ni dintel: el hueco queda de suelo a techo."""
        t = o["thickness"] / 2 + 0.002
        if o["axis"] == 0:
            return box(o["start"], o["perp"] - t, o["end"], o["perp"] + t)
        return box(o["perp"] - t, o["start"], o["perp"] + t, o["end"])

    # ---------------- franjas horizontales ----------------
    levels = sorted({0.0, H} | {round(o["sill"], 3) for o in placed}
                    | {round(o["head"], 3) for o in placed})
    levels = [z for z in levels if 0 - 1e-6 <= z <= H + 1e-6]
    slabs = []
    mass_local = unary_union([Polygon([(x - x0, y - y0) for x, y in p.exterior.coords],
                                      [[(x - x0, y - y0) for x, y in i.coords] for i in p.interiors])
                              for p in explode(mass)])
    if placed:
        R_local = Polygon()
        R_local = unary_union([Polygon([(x - x0, y - y0) for x, y in g.exterior.coords],
                                       [[(x - x0, y - y0) for x, y in i.coords] for i in g.interiors])
                               for g in rooms_g])
        # el relleno del hueco no puede invadir la estancia: se recorta contra ella
        fill = unary_union([op_fill(o) for o in placed]).difference(R_local)
        mass_local = unary_union([mass_local, fill])
    for a, b in zip(levels, levels[1:]):
        if b - a < 1e-4:
            continue
        act = [o for o in placed if o["sill"] <= a + 1e-6 and o["head"] >= b - 1e-6]
        g = mass_local
        if act:
            g = g.difference(unary_union([op_rect(o) for o in act]))
        polys = [poly_out(p, 0, 0) for p in explode(g)]
        if polys:
            slabs.append({"z0": round(a, 3), "z1": round(b, 3), "polys": polys})

    # ---------------- salida ----------------
    rooms_out = []
    for r, g in zip(isl["rooms"], rooms_g):
        rp = g.representative_point()
        rooms_out.append({
            "name": r["name"], "area_decl": r["area_decl"],
            "area_calc": round(g.area, 3),
            "height": r["height"] or H,
            "height_source": r["height_source"],
            "poly": poly_out(g, x0, y0),
            "label_xy": [round(rp.x - x0, 3), round(rp.y - y0, 3)],
        })

    out_islands.append({
        "id": iid, "key": v["key"], "label": v["label"],
        "size": [round(x1 - x0, 3), round(y1 - y0, 3)],
        "height_max": H, "height_assumed": isl["height_assumed"],
        "area_total": round(sum(r["area_calc"] for r in rooms_out), 3),
        "area_total_decl": round(sum(r["area_decl"] for r in isl["rooms"]), 2),
        "rooms": rooms_out, "slabs": slabs, "openings": ops,
    })

    nv = sum(1 for o in ops if o["kind"].startswith("vent"))
    nvp = sum(1 for o in placed if o["kind"].startswith("vent"))
    report.append((v["label"], len(rooms_out), nvp, nv,
                   len(placed) - nvp, len(ops) - nv,
                   max(abs(r["area_calc"] - r["area_decl"]) for r in rooms_out)))

json.dump({"project": "LM20", "address": "Calle Luis Mitjans 20, 2º-6, Madrid",
           "studio": "Milímetro Arquitectura e Interiorismo",
           "units": "m", "islands": out_islands},
          open(DST, "w"), ensure_ascii=False, separators=(",", ":"))

print(f"{'variante':<20} {'estancias':>9} {'ventanas':>9} {'puertas':>9}  desv.max")
for lab, nr, nvp, nv, ndp, nd, da in report:
    print(f"{lab:<20} {nr:>9} {nvp:>4}/{nv:<4} {ndp:>4}/{nd:<4}  {da*10000:6.1f} cm2")
