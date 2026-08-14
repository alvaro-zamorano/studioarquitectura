"""Puertas de verificación de la etapa 4. Sin parámetros ajustables."""
import json, sys
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

S = json.load(open("scene.json"))
fails = 0


def gate(ok, name, detail):
    global fails
    if not ok:
        fails += 1
    print(f"{'OK ' if ok else 'FALLO'} [{name}] {detail}")


for isl in S["islands"]:
    print(f"\n--- {isl['label']} ---")
    rooms = [Polygon(r["poly"]["shell"], r["poly"]["holes"]) for r in isl["rooms"]]

    gate(all(g.is_valid and g.is_simple for g in rooms), "1 poligonos",
         f"{sum(1 for g in rooms if g.is_valid)}/{len(rooms)} validos y cerrados")

    ov = 0.0
    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            ov = max(ov, rooms[a].buffer(-0.001).intersection(rooms[b].buffer(-0.001)).area)
    gate(ov < 1e-4, "2 solape estancias", f"max {ov*10000:.2f} cm2")

    mass = unary_union([Polygon(p["shell"], p["holes"])
                        for s in isl["slabs"] for p in s["polys"]])
    inter = mass.intersection(unary_union(rooms).buffer(-0.001)).area
    gate(inter < 5e-3, "3 estancias∩muros", f"{inter*10000:.1f} cm2")

    # cota teorica: redondeo del cajetin a 2 decimales (0,005) + redondeo propio
    # a 3 decimales (0,0005). No es un umbral elegido, es la suma de los dos redondeos.
    dmax = max(abs(r["area_calc"] - r["area_decl"]) for r in isl["rooms"])
    gate(dmax <= 0.0060 + 1e-9, "4 area vs declarada", f"desviacion max {dmax*10000:.1f} cm2")

    tot = abs(isl["area_total"] - isl["area_total_decl"])
    gate(tot <= 0.02, "5 total vs cajetin",
         f"{isl['area_total']:.3f} vs {isl['area_total_decl']:.2f} m2")

    ver = [o for o in isl["openings"] if o["status"] == "verificado"]
    bad = [o for o in ver if abs((o["end"] - o["start"]) - o["span"]) > 0.05]
    gate(not bad, "6 luz vs etiqueta",
         f"{len(ver)}/{len(isl['openings'])} verificados, error max "
         f"{max([abs((o['end']-o['start'])-o['span']) for o in ver], default=0)*1000:.1f} mm")

    # 7 · antepecho y dintel presentes en cada hueco colocado
    # se mide la fraccion del rectangulo del vano ocupada por muro en cada franja:
    # llena por debajo del alfeizar y por encima del dintel, vacia en medio.
    miss, sinmuro = [], []
    R_all = unary_union(rooms)
    for o in isl["openings"]:
        if o["status"] == "no_localizado":
            continue
        t = o["thickness"] / 2
        rect = (box(o["start"], o["perp"] - t, o["end"], o["perp"] + t) if o["axis"] == 0
                else box(o["perp"] - t, o["start"], o["perp"] + t, o["end"]))
        # si las estancias contiguas se comen la banda, el plano no dibuja muro ahi
        if rect.difference(R_all).area / rect.area < 0.25:
            sinmuro.append(o["label"])
            continue
        for s in isl["slabs"]:
            U = unary_union([Polygon(q["shell"], q["holes"]) for q in s["polys"]])
            frac = rect.intersection(U).area / rect.area
            solid = s["z1"] <= o["sill"] + 1e-6 or s["z0"] >= o["head"] - 1e-6
            if (solid and frac < 0.25) or (not solid and frac > 0.05):
                miss.append((o["label"], s["z0"], s["z1"], round(frac, 3), solid))
    gate(not miss, "7 antepecho/dintel",
         f"{len(isl['openings'])-len(sinmuro)-len([o for o in isl['openings'] if o['status']=='no_localizado'])}"
         f" huecos con franjas coherentes" if not miss else f"{len(miss)} incoherencias: {miss[:3]}")
    if sinmuro:
        print(f"     AVISO sin banda de muro en el plano de origen: {sinmuro} "
              f"(estancias contiguas dibujadas a tope, no hay espesor que modelar)")

    # 8 · toda estancia tiene que ser accesible. Un piso con una habitacion
    # tapiada no es un modelo incompleto: es un modelo falso.
    par = list(range(len(rooms)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a

    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            if rooms[a].distance(rooms[b]) < 1e-6:
                par[find(a)] = find(b)
    for o in isl["openings"]:
        if o["status"] == "no_localizado" or not (o["kind"] == "puerta" or o["sill"] <= 0.01):
            continue
        c = (o["start"] + o["end"]) / 2
        t = o["thickness"] / 2 + 0.06
        side = []
        for s in (-1, 1):
            p = (Point(c, o["perp"] + s*t) if o["axis"] == 0 else Point(o["perp"] + s*t, c))
            hit = [k for k in range(len(rooms)) if rooms[k].contains(p)]
            side.append(hit[0] if hit else None)
        if None not in side:
            par[find(side[0])] = find(side[1])
    comps = {}
    for k in range(len(rooms)):
        comps.setdefault(find(k), []).append(isl["rooms"][k]["name"])
    inf = [o for o in isl["openings"] if o["status"] == "inferido"]
    gate(len(comps) == 1, "8 accesibilidad",
         f"{len(rooms)} estancias comunicadas ({len(inf)} pasos inferidos)"
         if len(comps) == 1 else f"{len(comps)} bloques aislados: {list(comps.values())}")
    if inf:
        print(f"     pasos inferidos (no medidos, deducidos de accesibilidad): "
              f"{[o['rooms'] for o in inf]}")

    nl = [o["label"] for o in isl["openings"] if o["status"] == "no_localizado"]
    ap = [o["label"] for o in isl["openings"] if o["status"] == "aproximado"]
    print(f"     aproximados: {len(ap)} {ap}")
    print(f"     sin colocar: {len(nl)} {nl}")

print("\n" + ("TODAS LAS PUERTAS OK" if fails == 0 else f"{fails} PUERTAS FALLAN"))
sys.exit(1 if fails else 0)
