"""Tutor · generar preguntas con IA a partir de un tema libre o de las evidencias del estudiante."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..deps import asegurar_editable, evaluacion_del_tutor
from ..models import ContextoPregunta, Evaluacion, GeneracionIA, OpcionPregunta, Pregunta
from ..schemas import ArchivoRef, EvidenciaRef, GeneracionOut, GenerarIn, PreguntaOut
from ..security import Usuario, solo_tutor
from ..services.evidencias_client import EvidenciasError, get_evidencias_client
from ..services.generador import (
    ContextoVacioError, construir_peticion, normalizar_preguntas, reunir_contexto,
)
from ..services.llm import LLMError, get_provider

log = logging.getLogger("spp.evaluacion.generacion")
router = APIRouter(prefix="/tutor", tags=["Tutor · Generación con IA"])


@router.get("/evidencias", response_model=list[EvidenciaRef])
def listar_evidencias(id_practica: str = Query(..., max_length=30), user: Usuario = Depends(solo_tutor)):
    """Evidencias de la práctica (las provee el otro servicio) para elegirlas como contexto."""
    try:
        return [
            EvidenciaRef(
                id_evidencia=e.id_evidencia, descripcion=e.descripcion, horas_realizadas=e.horas_realizadas,
                id_actividad=e.id_actividad, nombre_actividad=e.nombre_actividad,
                archivos=[ArchivoRef(id_archivo=a.id_archivo, nombre=a.nombre, tipo_mime=a.mime) for a in e.archivos],
            )
            for e in get_evidencias_client().listar_evidencias(id_practica)
        ]
    except EvidenciasError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.post("/evaluaciones/{id_evaluacion}/generar", response_model=GeneracionOut,
             status_code=status.HTTP_201_CREATED)
def generar(body: GenerarIn, ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db),
            user: Usuario = Depends(solo_tutor), s: Settings = Depends(get_settings)):
    asegurar_editable(ev)
    t0 = time.monotonic()

    # 1) contexto (tema libre y/o evidencias del otro servicio)
    try:
        ctx = reunir_contexto(body.fuentes, get_evidencias_client(), s, ev.id_practica)
    except ContextoVacioError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except EvidenciasError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    # 2) proveedor y prompt
    try:
        proveedor = get_provider(s)
    except LLMError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    peticion = construir_peticion(ctx, body.cantidad, body.tipos, body.dificultad, body.instrucciones)

    # 3) se registra el intento ANTES de llamar a la IA: queda trazabilidad aunque falle
    gen = GeneracionIA(
        id_evaluacion=ev.id_evaluacion, id_tutor=user.id, cantidad_solicitada=body.cantidad,
        parametros={"tipos": body.tipos, "dificultad": body.dificultad, "instrucciones": body.instrucciones,
                    "valor_por_pregunta": body.valor_por_pregunta,
                    "fuentes": [f.model_dump(exclude={"texto"}) for f in body.fuentes]},
        proveedor=proveedor.nombre,
        modelo=s.llm_model_name,
        # solo las instrucciones; el contenido de las fuentes queda en contexto_pregunta
        prompt_usado=peticion.prompt.split("<fuente", 1)[0].strip(),
        estado="PENDIENTE",
    )
    db.add(gen)
    db.flush()
    for it in ctx.items:
        db.add(ContextoPregunta(
            id_evaluacion=ev.id_evaluacion, id_generacion=gen.id_generacion, tipo_fuente=it.tipo_fuente,
            id_referencia_externa=it.id_referencia, nombre=(it.nombre or "")[:255], texto_extraido=it.texto,
            caracteres=len(it.texto), truncado=it.truncado,
        ))
    db.commit()

    # 4) llamada a la IA + validación
    try:
        res = proveedor.generar(peticion)
        validas, avisos = normalizar_preguntas(res.preguntas, body.tipos, body.cantidad, body.dificultad)
        if not validas:
            raise LLMError("La IA no devolvió preguntas válidas. Intenta de nuevo o agrega más contexto.")
    except LLMError as e:
        gen.estado, gen.error = "FALLIDA", str(e)
        gen.duracion_ms = int((time.monotonic() - t0) * 1000)
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    except Exception as e:  # error inesperado: se deja constancia y se informa sin filtrar detalles
        log.exception("Fallo inesperado generando preguntas (generación %s)", gen.id_generacion)
        gen.estado, gen.error = "FALLIDA", f"Error interno: {e.__class__.__name__}"
        gen.duracion_ms = int((time.monotonic() - t0) * 1000)
        db.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno al generar las preguntas.")

    # 5) guardar como BORRADOR: el tutor las revisa antes de que cuenten
    orden = max((p.orden for p in ev.preguntas), default=0)
    creadas: list[Pregunta] = []
    for n, d in enumerate(validas, 1):
        p = Pregunta(
            id_evaluacion=ev.id_evaluacion, id_generacion=gen.id_generacion, tipo_pregunta=d["tipo_pregunta"],
            enunciado=d["enunciado"], valor_pregunta=body.valor_por_pregunta, orden=orden + n, origen="IA",
            estado_revision="BORRADOR", dificultad=d["dificultad"], respuesta_esperada=d["respuesta_esperada"],
            explicacion=d["explicacion"],
        )
        p.opciones = [OpcionPregunta(texto=o["texto"], es_correcta=o["es_correcta"], orden=i)
                      for i, o in enumerate(d["opciones"], 1)]
        db.add(p)
        creadas.append(p)

    gen.estado, gen.cantidad_generada = "COMPLETADA", len(creadas)
    gen.proveedor, gen.modelo = res.proveedor, res.modelo
    gen.tokens_entrada, gen.tokens_salida = res.tokens_entrada, res.tokens_salida
    gen.duracion_ms = int((time.monotonic() - t0) * 1000)
    db.commit()
    for p in creadas:
        db.refresh(p)
    db.refresh(gen)

    return GeneracionOut(
        **{k: getattr(gen, k) for k in ("id_generacion", "cantidad_solicitada", "cantidad_generada", "proveedor",
                                         "modelo", "estado", "error", "parametros", "created_at")},
        advertencias=ctx.advertencias + avisos,
        preguntas=[PreguntaOut.model_validate(p) for p in creadas],
    )
