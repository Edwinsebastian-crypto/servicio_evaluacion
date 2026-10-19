"""Dependencias y verificaciones compartidas por los routers."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import Evaluacion, IntentoEvaluacion, Pregunta, Respuesta
from .security import Usuario, solo_estudiante, solo_tutor


def evaluacion_del_tutor(id_evaluacion: int, db: Session = Depends(get_db),
                         user: Usuario = Depends(solo_tutor)) -> Evaluacion:
    ev = db.get(Evaluacion, id_evaluacion)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La evaluación no existe.")
    if ev.id_tutor != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta evaluación pertenece a otro tutor.")
    return ev


def pregunta_del_tutor(id_pregunta: int, db: Session = Depends(get_db),
                       user: Usuario = Depends(solo_tutor)) -> Pregunta:
    p = db.get(Pregunta, id_pregunta)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La pregunta no existe.")
    if p.evaluacion.id_tutor != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta pregunta pertenece a otro tutor.")
    return p


def intento_del_tutor(id_intento: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(solo_tutor)) -> IntentoEvaluacion:
    i = db.get(IntentoEvaluacion, id_intento)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El intento no existe.")
    if i.evaluacion.id_tutor != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este intento pertenece a otro tutor.")
    return i


def respuesta_del_tutor(id_respuesta: int, db: Session = Depends(get_db),
                        user: Usuario = Depends(solo_tutor)) -> Respuesta:
    r = db.get(Respuesta, id_respuesta)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La respuesta no existe.")
    if r.intento.evaluacion.id_tutor != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta respuesta pertenece a otro tutor.")
    return r


def asegurar_editable(ev: Evaluacion) -> None:
    """Las preguntas solo se pueden tocar mientras nadie haya presentado la evaluación."""
    if ev.estado == "CERRADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación está cerrada.")
    if ev.intentos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ya hay intentos presentados; no se pueden modificar las preguntas. Puedes cerrar la evaluación.",
        )


def intento_del_estudiante(id_intento: int, db: Session = Depends(get_db),
                           user: Usuario = Depends(solo_estudiante)) -> IntentoEvaluacion:
    i = db.get(IntentoEvaluacion, id_intento)
    if i is None or i.id_estudiante != user.id:
        # mismo mensaje para no revelar si existe
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El intento no existe.")
    return i
