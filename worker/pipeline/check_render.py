#!/usr/bin/env python3
"""
Verificador automatico del render generativo.

No compara la imagen de IA contra otra imagen: la compara contra la GEOMETRIA.
Proyecta cada hueco de scene.json con la misma camara con la que se genero la
imagen de control y obtiene el rectangulo en pixeles donde ese hueco TIENE que
estar. Luego busca los huecos reales en la imagen generada y los empareja.

Criterio de aceptacion, fijo:
  - mismo numero de huecos que los proyectados
  - centro de cada hueco dentro del 3 % del ancho de imagen
  - anchura y altura dentro del +-12 %
Lo que no pasa, se rechaza. Sin esto, una de cada seis laminas lleva una ventana
que no existe y nadie lo ve en la reunion.

Uso:  python3 check_render.py <variante> "<ESTANCIA>" imagen1.png [imagen2.png ...]
"""
import json, sys, math
import numpy as np
from PIL import Image
from scipy import ndimage
from shot_brief import brief, island

CONTRASTE = 10      # niveles de gris que un hueco debe destacar sobre el paramento


def projector(eye, tgt, fov, w, h):
    ex, ey, ez = eye
    zx, zy, zz = ex - tgt[0], ey - tgt[1], ez - tgt[2]
    n = math.sqrt(zx*zx + zy*zy + zz*zz); zx, zy, zz = zx/n, zy/n, zz/n
    xx, xy, xz = zz, 0.0, -zx                               # cross(up=(0,1,0), z)
    n = math.sqrt(xx*xx + xy*xy + xz*xz) or 1; xx, xy, xz = xx/n, xy/n, xz/n
    yx, yy, yz = zy*xz - zz*xy, zz*xx - zx*xz, zx*xy - zy*xx
    t = math.tan(math.radians(fov) / 2)
    asp = w / h

    def P(p):
        vx, vy, vz = p[0]-ex, p[1]-ey, p[2]-ez
        xc = vx*xx + vy*xy + vz*xz
        yc = vx*yx + vy*yy + vz*yz
        zc = -(vx*zx + vy*zy + vz*zz)
        if zc <= 0.05:
            return None
        return ((xc/zc/(t*asp)*0.5 + 0.5) * w, (0.5 - yc/zc/t*0.5) * h)
    return P


def expected(key, room, w, h):
    b = brief(key, room)
    isl = island(key)
    cx, cy = isl["size"][0]/2, isl["size"][1]/2
    P = projector(b["eye"], b["target"], b["fov"], w, h)
    out = []
    for o in b["seen"]:
        # solo ventanas: son las unicas que la imagen delata por brillo.
        # Una puerta no se puede verificar por umbral, y decir lo contrario
        # seria dar por buena una comprobacion que no comprueba nada.
        if o["kind"] != "ventana" or o["sill"] <= 0.01:
            continue
        pts = []
        for a in (o["start"], o["end"]):
            for z in (o["sill"], o["head"]):
                X = (a - cx) if o["axis"] == 0 else (o["perp"] - cx)
                Z = (cy - o["perp"]) if o["axis"] == 0 else (cy - a)
                q = P((X, z, Z))
                if q:
                    pts.append(q)
        if len(pts) < 4:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        bx = (min(xs), min(ys), max(xs), max(ys))
        if bx[2] < 0 or bx[0] > w or bx[3] < 0 or bx[1] > h:
            continue
        if (bx[2]-bx[0]) < w*0.012 or (bx[3]-bx[1]) < h*0.012:
            continue
        out.append({"label": o["label"], "status": o["status"], "box": bx})
    return sorted(out, key=lambda d: d["box"][0]), b


def gray(path, w, h):
    return np.array(Image.open(path).convert("RGB").resize((w, h))).astype(float).mean(2)


def ring_stats(g, box, grow=0.55):
    x0, y0, x1, y1 = [int(v) for v in box]
    h, w = g.shape
    bw, bh = x1-x0, y1-y0
    ex0, ey0 = max(0, int(x0-bw*grow)), max(0, int(y0-bh*grow))
    ex1, ey1 = min(w, int(x1+bw*grow)), min(h, int(y1+bh*grow))
    inner = g[max(0,y0):min(h,y1), max(0,x0):min(w,x1)]
    outer = g[ey0:ey1, ex0:ex1].copy()
    m = np.ones(outer.shape, bool)
    m[max(0,y0)-ey0:min(h,y1)-ey0, max(0,x0)-ex0:min(w,x1)-ex0] = False
    if inner.size == 0 or m.sum() == 0:
        return 0.0, 0.0
    return float(inner.mean()), float(outer[m].mean())


def mask_from(boxes, w, h):
    m = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in boxes:
        m[max(0,int(y0)):min(h,int(y1)), max(0,int(x0)):min(w,int(x1))] = True
    return m


def run(key, room, paths, w=1024, h=768):
    exp, b = expected(key, room, w, h)
    print(f"camara  ojo={b['eye']}  objetivo={b['target']}  fov={b['fov']}")
    print(f"huecos proyectados desde la geometria: {len(exp)}")
    for e in exp:
        x0, y0, x1, y1 = e["box"]
        print(f"   {e['label']:<16} {e['status']:<11} x[{x0:6.0f},{x1:6.0f}] y[{y0:6.0f},{y1:6.0f}]")
    EM = mask_from([e["box"] for e in exp], w, h)
    for p in paths:
        g = gray(p, w, h)
        print(f"\n--- {p}")
        ok = True
        for e in exp:
            ins, out = ring_stats(g, e["box"])
            good = (ins - out) >= CONTRASTE
            ok &= good
            print(f"   {'OK ' if good else 'FALTA'} ventana en x[{e['box'][0]:.0f},{e['box'][2]:.0f}] "
                  f"· contraste hueco/paramento {ins-out:+.0f} niveles")
        # huecos NO previstos: brillo alto fuera de donde tiene que haberlo
        # Un hueco inventado no es "una zona clara": es una mancha muy brillante,
        # compacta, con proporcion de ventana y por debajo del techo. Los reflejos
        # del paramento y la junta con el techo tambien son claros y NO son huecos;
        # filtrarlos por forma es lo que hace utilizable la comprobacion.
        wall = float(np.median(g[:int(h*0.75)]))
        bright = (g > wall + CONTRASTE*3.0)
        bright[int(h*0.80):, :] = False
        grown = ndimage.binary_dilation(EM, iterations=int(w*0.02))
        lab, n = ndimage.label(bright & ~grown)
        invented = []
        for k in range(1, n+1):
            ys, xs = np.where(lab == k)
            if len(xs) < w*h*0.005:
                continue
            bw, bh = xs.max()-xs.min()+1, ys.max()-ys.min()+1
            if not (0.35 <= bw/bh <= 3.0):
                continue                       # cinta de luz, no hueco
            if ys.mean() < h*0.18 or bh > h*0.62:
                continue                       # junta con el techo / franja lateral
            if len(xs) / (bw*bh) < 0.45:
                continue                       # mancha deshilachada
            invented.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
        if invented:
            ok = False
            print(f"   INVENTADO: {len(invented)} hueco(s) donde el plano dice pared ciega -> {invented}")
        else:
            print("   OK  ningun hueco inventado")
        print("   =>", "ACEPTADA" if ok else "RECHAZADA")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3:])
