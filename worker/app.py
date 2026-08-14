#!/usr/bin/env python3
"""
API del worker. Fase 0: un solo estudio, sin auth, estado en disco.

    POST /jobs                 multipart: dwg=<fichero> [pdf=<fichero>]
    GET  /jobs/{id}            estado + resultado de las puertas
    GET  /jobs/{id}/overlay    la superposicion 2D  <- lo que mira el humano
    POST /jobs/{id}/approve    pasa la puerta 7 y devuelve el enlace
    GET  /p/{token}/           el visor publico
    GET  /p/{token}/offline    el visor autocontenido, para mandar por correo

Lo que NO hace, a proposito:
  - No hay cola: el pipeline tarda ~3 s con un plano tipo, asi que ejecutar en
    background dentro del proceso llega de sobra. QStash entra cuando entren los
    renders generativos, que si tardan minutos.
  - No hay base de datos: `job.json` en disco. Supabase entra en F1, con el
    multi-estudio. Meterla antes es resolver un problema que aun no existe.
  - No hay auth: el enlace publico es un token de 16 hex que no se adivina.

Las dos cosas que si estan desde el primer dia porque despues no se ponen:
  - El corte en `revision_humana`. Ninguna ruta devuelve un enlace sin que
    alguien haya llamado a /approve.
  - La salida integra de cada verificador se guarda en el trabajo. Cuando el
    estudio pregunte de donde sale un numero, hay una respuesta que no es "confia".
"""
from __future__ import annotations

from fastapi import FastAPI, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import run_pipeline as rp

api = FastAPI(title="plano-3d worker", version="0.1")

MAX_DWG = 60 * 1024 * 1024   # un DWG de vivienda va muy por debajo


@api.get("/health")
def health():
    from shutil import which
    return {"ok": True, "dwg2dxf": bool(which("dwg2dxf")), "work_root": str(rp.WORK_ROOT)}


@api.post("/jobs", status_code=202)
async def crear(background: BackgroundTasks,
                dwg: UploadFile = File(...),
                pdf: UploadFile | None = File(None)):
    if not dwg.filename.lower().endswith(".dwg"):
        raise HTTPException(400, "se espera un .dwg")
    data = await dwg.read()
    if not data:
        raise HTTPException(400, "el fichero viene vacio")
    if len(data) > MAX_DWG:
        raise HTTPException(413, f"el DWG pasa de {MAX_DWG // 1024 // 1024} MB")

    job = rp.create(data, await pdf.read() if pdf else None)
    background.add_task(rp.process, job)
    return {"id": job.id, "status": job.status,
            "seguimiento": f"/jobs/{job.id}"}


@api.get("/jobs/{job_id}")
def estado(job_id: str):
    job = _get(job_id)
    body = {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "pasos": [{"nombre": s.name, "ok": s.ok, "segundos": s.seconds,
                   "error": s.error, "salida": s.stdout} for s in job.steps],
    }
    if job.status == "revision_humana":
        body["siguiente"] = {
            "mira": f"/jobs/{job.id}/overlay",
            "aprueba": f"POST /jobs/{job.id}/approve",
            "aviso": ("Las puertas de maquina estan en verde. Falta la puerta 7: "
                      "un humano tiene que ver la superposicion sobre el plano "
                      "original antes de que esto salga a un cliente."),
        }
    if job.token:
        body["enlace"] = f"/p/{job.token}/"
        body["offline"] = f"/p/{job.token}/offline"
    return body


@api.get("/jobs/{job_id}/overlay")
def overlay(job_id: str):
    job = _get(job_id)
    f = job.work / "overlay.html"
    if not f.exists():
        raise HTTPException(404, "todavia no hay superposicion")
    return FileResponse(f, media_type="text/html")


@api.post("/jobs/{job_id}/approve")
def aprobar(job_id: str):
    job = _get(job_id)
    try:
        job = rp.approve(job)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": job.id, "status": job.status,
            "enlace": f"/p/{job.token}/", "offline": f"/p/{job.token}/offline"}


@api.get("/p/{token}/")
def visor(token: str):
    return _publico(token, "index.html")


@api.get("/p/{token}/offline")
def visor_offline(token: str):
    return _publico(token, "offline.html")


def _publico(token: str, nombre: str):
    if not token.isalnum():
        raise HTTPException(404, "no existe")
    f = rp.WORK_ROOT / "public" / token / nombre
    if not f.exists():
        raise HTTPException(404, "no existe")
    return FileResponse(f, media_type="text/html")


def _get(job_id: str) -> rp.Job:
    if "/" in job_id or ".." in job_id:
        raise HTTPException(400, "id no valido")
    job = rp.load(job_id)
    if job is None:
        raise HTTPException(404, "no existe ese trabajo")
    return job


@api.exception_handler(Exception)
async def _boom(request, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)})
