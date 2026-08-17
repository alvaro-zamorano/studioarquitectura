#!/usr/bin/env python3
"""
Orquestador de un trabajo: DWG -> visor.

Llama a los scripts del pipeline COMO SUBPROCESOS y no los modifica. Esa es la
regla: `pipeline.py`, `build_scene.py` y `verify.py` estan verificados contra el
plano de Milimetro y cualquier cambio para "encajar" con el servicio invalida esa
verificacion. El orquestador se adapta a ellos, nunca al reves.

Estados:

    recibido -> ingest -> extract -> cobertura -> verify2d -> build3d -> verify3d
             -> publish -> revision_humana  (aqui se para: alguien mira)
             -> publicado

El corte en `revision_humana` es la puerta 7 y no se automatiza: es la unica
comprobacion que detecta una extraccion numericamente correcta pero
geometricamente falsa. Si esto se salta, el servicio deja de valer.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PIPE = Path(__file__).parent / "pipeline"
WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/data"))

# Frase centinela que imprimen los verificadores. Se comprueba junto al codigo de
# salida: si un dia cambia el texto, el trabajo falla en vez de darse por bueno.
OK = "TODAS LAS PUERTAS OK"


@dataclass
class Step:
    name: str
    ok: bool
    seconds: float
    stdout: str = ""
    error: str = ""


@dataclass
class Job:
    id: str
    root: Path
    status: str = "recibido"
    steps: list = field(default_factory=list)
    token: str = ""
    error: str = ""

    @property
    def work(self) -> Path:
        return self.root / "work"

    def save(self) -> None:
        (self.root / "job.json").write_text(json.dumps({
            "id": self.id,
            "status": self.status,
            "token": self.token,
            "error": self.error,
            "steps": [s.__dict__ for s in self.steps],
        }, ensure_ascii=False, indent=1), encoding="utf-8")


def _run(job: Job, name: str, args: list[str], cwd: Path,
         expect_gates: bool = False) -> bool:
    t0 = time.monotonic()
    env = {**os.environ, "PYTHONPATH": str(PIPE)}
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0 and (not expect_gates or OK in out)
    err = ""
    if p.returncode != 0:
        err = f"salida {p.returncode}"
    elif expect_gates and OK not in out:
        err = f"no aparece «{OK}» en la salida del verificador"
    job.steps.append(Step(name, ok, round(time.monotonic() - t0, 2), out.strip(), err))
    job.save()
    return ok


def process(job: Job) -> Job:
    """Recorre el pipeline hasta la puerta humana. No publica."""
    job.work.mkdir(parents=True, exist_ok=True)
    dwg = job.root / "in" / "original.dwg"
    dxf = job.work / "plano.dxf"

    stages = [
        ("ingest",   [sys.executable, str(PIPE / "pipeline.py"), "ingest",
                      str(dwg), str(dxf)], False),
        ("extract",  [sys.executable, str(PIPE / "pipeline.py"), "extract",
                      str(dxf), "model.json"], False),
        # Cobertura antes de correccion: las otras puertas comprueban que lo
        # extraido esta bien, esta comprueba que no falte nada. Va aqui porque si
        # el plano usa convenciones que no sabemos leer, seguir es perder tiempo
        # y acabar con un modelo plausible e incompleto.
        ("cobertura", [sys.executable, str(PIPE / "verify_coverage.py"),
                       str(dxf), "model.json"], True),
        ("verify2d", [sys.executable, str(PIPE / "pipeline.py"), "verify",
                      "model.json", str(dxf), "overlay.html"], True),
        ("build3d",  [sys.executable, str(PIPE / "build_scene.py"),
                      "model.json", "scene.json"], False),
        ("verify3d", [sys.executable, str(PIPE / "verify.py")], True),
        ("publish",  [sys.executable, str(PIPE / "publish.py"),
                      str(job.work), str(PIPE)], False),
    ]

    for name, args, gates in stages:
        job.status = name
        job.save()
        if not _run(job, name, args, job.work, gates):
            job.status = "fallo"
            job.error = job.steps[-1].error or f"fallo en {name}"
            job.save()
            return job

    # Todo verde por maquina. Ahora tiene que mirarlo una persona.
    job.status = "revision_humana"
    job.save()
    return job


def approve(job: Job) -> Job:
    """La puerta 7 la ha pasado un humano. Solo aqui aparece el enlace."""
    if job.status != "revision_humana":
        raise ValueError(f"no se puede aprobar un trabajo en estado «{job.status}»")
    job.token = secrets.token_hex(8)
    pub = WORK_ROOT / "public" / job.token
    pub.mkdir(parents=True, exist_ok=True)
    shutil.copy(job.work / "viewer-web.html", pub / "index.html")
    shutil.copy(job.work / "viewer-offline.html", pub / "offline.html")
    job.status = "publicado"
    job.save()
    return job


def load(job_id: str) -> Job | None:
    root = WORK_ROOT / "jobs" / job_id
    f = root / "job.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    j = Job(id=d["id"], root=root, status=d["status"],
            token=d.get("token", ""), error=d.get("error", ""))
    j.steps = [Step(**s) for s in d.get("steps", [])]
    return j


def create(dwg_bytes: bytes, pdf_bytes: bytes | None = None) -> Job:
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    root = WORK_ROOT / "jobs" / job_id
    (root / "in").mkdir(parents=True, exist_ok=True)
    (root / "in" / "original.dwg").write_bytes(dwg_bytes)
    if pdf_bytes:
        (root / "in" / "plano.pdf").write_bytes(pdf_bytes)
    j = Job(id=job_id, root=root)
    j.save()
    return j


if __name__ == "__main__":
    # Uso en local sin servidor:  python3 run_pipeline.py plano.dwg
    src = Path(sys.argv[1])
    j = create(src.read_bytes())
    print(f"job {j.id}")
    j = process(j)
    for s in j.steps:
        print(f"  {'OK  ' if s.ok else 'FALLA'} {s.name:9} {s.seconds:6.2f}s {s.error}")
    print(f"estado: {j.status}")
    if j.status == "revision_humana":
        print(f"mira {j.work / 'overlay.html'} y luego aprueba")
