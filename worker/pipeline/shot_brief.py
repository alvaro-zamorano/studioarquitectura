#!/usr/bin/env python3
"""
scene.json -> (camara, prompt)  para el render generativo.

La idea: el modelo de imagen no tiene por que adivinar nada que ya esta medido.
En vez de un prompt de adjetivos ("salon luminoso"), se le pasa el INVENTARIO de
la estancia sacado del propio DWG: superficie, altura libre, cuantos huecos hay,
en que pared cae cada uno, su anchura, su altura y su antepecho, y — sobre todo —
que paredes son ciegas. El fallo caro del POC fue una ventana inventada en un
testero; eso se combate nombrando el testero como ciego, no subiendo la CFG.

Uso:
    python3 shot_brief.py reformado "SALÓN"          # imprime camara + prompt
    python3 shot_brief.py --list                     # estancias disponibles
"""
import json, sys, math
from shapely.geometry import Polygon, box, Point

S = json.load(open("scene.json"))
EYE_H = 1.55          # altura de camara: ojo de una persona de pie
TGT_H = 1.25          # se mira al centro del hueco, no al techo


def island(key):
    for i in S["islands"]:
        if i["key"] == key:
            return i
    raise SystemExit(f"variante desconocida: {key}")


def op_rect(o):
    t = o["thickness"] / 2
    return (box(o["start"], o["perp"] - t, o["end"], o["perp"] + t) if o["axis"] == 0
            else box(o["perp"] - t, o["start"], o["perp"] + t, o["end"]))


def brief(key, room_name):
    isl = island(key)
    room = next((r for r in isl["rooms"] if r["name"] == room_name), None)
    if room is None:
        raise SystemExit(f"estancia desconocida: {room_name}")
    poly = Polygon(room["poly"]["shell"], room["poly"]["holes"])
    x0, y0, x1, y1 = poly.bounds
    W, D = x1 - x0, y1 - y0
    H = room["height"]

    mine = []
    for o in isl["openings"]:
        if o["status"] == "no_localizado":
            continue
        if op_rect(o).distance(poly) < 0.06:
            mine.append(o)

    # masa de muro a la altura del ojo: sirve para saber que se ve de verdad.
    # Dos estancias que se tocan a distancia cero no tienen tabique entre medias,
    # asi que desde el salon se ve la ventana de la cocina. El brief tiene que
    # describir LO QUE ENTRA EN EL ENCUADRE, no lo que pertenece a la estancia.
    slab = next((s for s in isl["slabs"] if s["z0"] <= EYE_H < s["z1"]), isl["slabs"][0])
    from shapely.ops import unary_union
    MASS = unary_union([Polygon(p["shell"], p["holes"]) for p in slab["polys"]])

    # ---- pared de cada hueco, y camara ----
    # se mira hacia la pared con mas huecos; si empatan, hacia la mas ancha
    walls = {}
    for o in mine:
        # clave de pared: (eje, lado). lado = +1 si el hueco esta por encima del
        # centro de la estancia en la perpendicular
        c = poly.representative_point()
        ref = c.y if o["axis"] == 0 else c.x
        walls.setdefault((o["axis"], 1 if o["perp"] > ref else -1), []).append(o)

    def wall_score(k):
        ax, side = k
        wins = [o for o in walls[k] if o["kind"] == "ventana"]
        return (len(wins), sum(o["span"] for o in walls[k]))

    main = max(walls, key=wall_score) if walls else (0, 1)
    ax, side = main
    # Camara de esquina, que es como se fotografia un interior: se planta en el
    # rincon opuesto al pano principal y mira en diagonal. Asi entran dos o tres
    # paredes y la estancia se lee; una camara centrada en una habitacion de 3,6 m
    # solo ve un pano y no dice nada.
    ins = 0.40
    if walls:
        oc = walls[main][0]
        tgt = (((oc["start"] + oc["end"]) / 2, oc["perp"]) if ax == 0
               else (oc["perp"], (oc["start"] + oc["end"]) / 2))
    else:
        tgt = ((x0 + x1) / 2, y1)
    corners = [(cx_, cy_) for cx_ in (x0 + ins, x1 - ins) for cy_ in (y0 + ins, y1 - ins)]
    corners = [c for c in corners if poly.buffer(-0.05).contains(Point(c))] or corners
    eye = max(corners, key=lambda c: math.hypot(c[0] - tgt[0], c[1] - tgt[1]))

    # coordenadas del visor: X = x - cx,  Z = cy - y
    cx, cy = isl["size"][0] / 2, isl["size"][1] / 2
    EYE = (round(eye[0] - cx, 3), EYE_H, round(cy - eye[1], 3))
    TGT = (round(tgt[0] - cx, 3), TGT_H, round(cy - tgt[1], 3))

    # ---- clasificacion de paredes respecto a la camara ----
    dirx, dirz = TGT[0] - EYE[0], TGT[2] - EYE[2]
    n = math.hypot(dirx, dirz) or 1
    dirx, dirz = dirx / n, dirz / n
    rgtx, rgtz = -dirz, dirx

    def where(o):
        px = ((o["start"] + o["end"]) / 2 if o["axis"] == 0 else o["perp"]) - cx
        pz = cy - (o["perp"] if o["axis"] == 0 else (o["start"] + o["end"]) / 2)
        vx, vz = px - EYE[0], pz - EYE[2]
        fwd = vx * dirx + vz * dirz
        rgt = vx * rgtx + vz * rgtz
        if abs(fwd) >= abs(rgt):
            return "frontal" if fwd > 0 else "trasera"
        return "derecha" if rgt > 0 else "izquierda"

    from shapely.geometry import LineString
    FOV_V = 60.0
    HALF = math.atan(math.tan(math.radians(FOV_V)/2) * 4/3)   # semiangulo horizontal real

    def visible(o):
        px = (o["start"] + o["end"]) / 2 if o["axis"] == 0 else o["perp"]
        py = o["perp"] if o["axis"] == 0 else (o["start"] + o["end"]) / 2
        vx, vz = px - eye[0], (eye[1] - py)
        # angulo respecto al eje de camara (en coordenadas de planta)
        dx, dy = tgt[0] - eye[0], tgt[1] - eye[1]
        nn = math.hypot(dx, dy) or 1
        cosang = ((px - eye[0]) * dx + (py - eye[1]) * dy) / (nn * (math.hypot(px - eye[0], py - eye[1]) or 1))
        if cosang < math.cos(HALF):
            return False
        ray = LineString([(eye[0], eye[1]), (px, py)])
        return ray.intersection(MASS).length < 0.02

    seen = [o for o in mine if visible(o)] + \
           [o for o in isl["openings"]
            if o["status"] != "no_localizado" and o not in mine and visible(o)]

    groups = {"frontal": [], "izquierda": [], "derecha": [], "trasera": []}
    for o in seen:
        groups[where(o)].append(o)

    def describe(o):
        k = "ventana" if o["kind"] == "ventana" and o["sill"] > 0.01 else (
            "puerta" if o["kind"] == "puerta" else "puerta balconera")
        s = f"{k} de {o['span']:.2f} m de ancho x {o['h']:.2f} m de alto"
        if o["sill"] > 0.01:
            s += f", antepecho a {o['sill']:.2f} m del suelo"
        s += f", mocheta de {o['thickness']:.2f} m"
        if o["status"] == "inferido":
            s += " [posicion deducida, no medida]"
        return s

    ES = {"frontal": "la pared de enfrente", "izquierda": "la pared de la izquierda",
          "derecha": "la pared de la derecha", "trasera": "la pared de detras de la camara"}
    lines, blind = [], []
    for g in ("frontal", "izquierda", "derecha"):
        if groups[g]:
            uniq = {}
            for o in groups[g]:
                uniq.setdefault(describe(o), 0)
                uniq[describe(o)] += 1
            det = "; ".join((f"{n} iguales: {d}" if n > 1 else d) for d, n in uniq.items())
            lines.append(f"- En {ES[g]} se ven EXACTAMENTE {len(groups[g])} hueco(s): {det}.")
        else:
            blind.append(ES[g])

    inventory = "\n".join(lines)
    if blind:
        inventory += ("\n- " + " y ".join(blind).capitalize()
                      + (" es" if len(blind) == 1 else " son")
                      + " COMPLETAMENTE CIEGA" + ("" if len(blind) == 1 else "S")
                      + ": no tiene ningun hueco, ni ventana ni puerta. No anadas ninguno.")

    prompt = f"""Fotografia de interiorismo de esta misma estancia, ya reformada. La imagen adjunta es el levantamiento medido: manda ella, no tu criterio.

DATOS DEL LEVANTAMIENTO (no son sugerencias, son medidas)
- Estancia: {room_name}, {room['area_calc']:.2f} m2 utiles, {W:.2f} x {D:.2f} m en planta.
- Altura libre: {H:.2f} m{' (asumida)' if room['height_source'] == 'asumida' else ''}.
- Huecos visibles en este encuadre: {len(seen)} (la estancia tiene {len(mine)}).
{inventory}

QUE DEBE QUEDAR IDENTICO A LA IMAGEN ADJUNTA
La camara, la perspectiva y el punto de fuga. Las lineas de encuentro suelo-pared,
pared-pared y pared-techo. La posicion, el ancho, el alto y el alfeizar de cada
hueco, y la profundidad de sus mochetas. El numero de huecos por pared.

QUE PUEDES CAMBIAR
Solo el acabado y la luz: yeso blanco mate liso en paredes y techo, tarima de roble
claro de lama ancha, carpinteria de aluminio blanco de perfil fino con vidrio
transparente y vistas desenfocadas de tejados de Madrid, mochetas enyesadas en
blanco, rodapie blanco de 7 cm. Luz de dia cubierta entrando por los huecos,
sombras suaves, sin mancha de sol directo.

PROHIBIDO
Anadir, mover, ensanchar o estrechar cualquier hueco. Abrir una ventana en una
pared que arriba figura como ciega. Cambiar la altura del techo o la proporcion de
la estancia. Curvar las verticales.

FORMATO
Fotografia de arquitectura, full frame 24 mm, verticales aplomadas, balance de
blancos neutro, sin vineteado."""

    return {"eye": EYE, "target": TGT, "fov": FOV_V, "variant": key, "room": room_name,
            "openings": len(seen), "room_openings": len(mine), "seen": seen, "prompt": prompt}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for i in S["islands"]:
            print(i["key"], "->", ", ".join(r["name"] for r in i["rooms"]))
        raise SystemExit
    b = brief(sys.argv[1], sys.argv[2])
    print(json.dumps({k: v for k, v in b.items() if k != "prompt"}, ensure_ascii=False))
    print("\n" + b["prompt"])
