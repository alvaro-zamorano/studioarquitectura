"""Localizacion geometrica de vanos. Sin parametros ajustables.

El punto (x,y) que trae model.json cae DENTRO de la banda de muro, dentro del
hueco. El vano se obtiene lanzando rayos desde ese punto:

  - a lo largo del eje del muro el rayo choca contra los dos munones -> la luz
    libre medida es el vano.
  - perpendicular al muro el rayo sale al exterior o a la estancia -> luz grande.

El eje es aquel cuya luz libre coincide con la anchura de la etiqueta de texto
(fuente independiente, HANDOFF 6.6). Es una comprobacion binaria: si ningun eje
coincide dentro de 5 cm, el vano se marca como no colocado y se reporta.
"""
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

TOL = 0.05      # 5 cm contra la etiqueta de texto. No se toca para hacer pasar nada.
REACH = 6.0


def _free_run(UW, x, y, axis):
    """(d_neg, d_pos) hasta el primer material en cada sentido del eje."""
    if axis == 0:
        ln = LineString([(x - REACH, y), (x + REACH, y)])
    else:
        ln = LineString([(x, y - REACH), (x, y + REACH)])
    it = ln.intersection(UW)
    if it.is_empty:
        return None, None
    segs = [it] if it.geom_type == "LineString" else [g for g in it.geoms if g.geom_type == "LineString"]
    c = x if axis == 0 else y
    dn = dp = None
    for s in segs:
        b = s.bounds
        lo, hi = (b[0], b[2]) if axis == 0 else (b[1], b[3])
        if hi <= c and (dn is None or c - hi < dn):
            dn = c - hi
        if lo >= c and (dp is None or lo - c < dp):
            dp = lo - c
    return dn, dp


def locate(UW, x, y, span):
    """-> dict(axis, start, end, center, thickness, perp_center) o None."""
    best = None
    for axis in (0, 1):
        dn, dp = _free_run(UW, x, y, axis)
        if dn is None or dp is None:
            continue
        gap = dn + dp
        err = abs(gap - span)
        if err <= TOL and (best is None or err < best[0]):
            best = (err, axis, dn, dp, gap)
    if best is None:
        return None
    err, axis, dn, dp, gap = best
    c = x if axis == 0 else y
    start, end = c - dn, c + dp
    # espesor: rayo perpendicular clavado 2 cm dentro del munon
    ths = []
    for probe in (start - 0.02, end + 0.02):
        px, py = (probe, y) if axis == 0 else (x, probe)
        if axis == 0:
            ln = LineString([(px, py - 2.0), (px, py + 2.0)])
        else:
            ln = LineString([(px - 2.0, py), (px + 2.0, py)])
        it = ln.intersection(UW)
        if it.is_empty:
            continue
        segs = [it] if it.geom_type == "LineString" else [g for g in it.geoms if g.geom_type == "LineString"]
        k = y if axis == 0 else x
        segs = [s for s in segs
                if (s.bounds[1] - 0.01 <= k <= s.bounds[3] + 0.01) if axis == 0
                or (s.bounds[0] - 0.01 <= k <= s.bounds[2] + 0.01)]
        if not segs:
            continue
        s = min(segs, key=lambda s2: abs(((s2.bounds[1] + s2.bounds[3]) / 2 if axis == 0
                                          else (s2.bounds[0] + s2.bounds[2]) / 2) - k))
        b = s.bounds
        lo, hi = (b[1], b[3]) if axis == 0 else (b[0], b[2])
        ths.append((hi - lo, (lo + hi) / 2))
    if not ths:
        return None
    th, pc = min(ths, key=lambda t: t[0])
    return {"axis": axis, "start": start, "end": end, "center": (start + end) / 2,
            "gap": gap, "thickness": th, "perp_center": pc, "err": err}
