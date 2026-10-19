"""Tutor · crear, editar, publicar y cerrar evaluaciones."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import evaluacion_del_tutor
from ..models import Evaluacion
from ..schemas import EvaluacionCreate, EvaluacionDetalle, EvaluacionPatch, EvaluacionResumen
from ..security import Usuario, solo_tutor
from ..serializers import detalle, resumen
from ..services.calificacion import actualizar_nota_final, finalizar_intento

router = APIRouter(prefix="/tutor", tags=["Tutor · Evaluaciones"])


@router.get("/evaluaciones", response_model=list[EvaluacionResumen])
def listar(
    id_practica: str | None = Query(default=None, max_length=30),
    estado: str | None = Query(default=None, pattern="^(BORRADOR|PUBLICADA|CERRADA)$"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(solo_tutor),
):
    q = (select(Evaluacion).where(Evaluacion.id_tutor == user.id)
         .options(selectinload(Evaluacion.preguntas), selectinload(Evaluacion.intentos))
         .order_by(Evaluacion.id_evaluacion.desc()))
    if id_practica is not None:
        q = q.where(Evaluacion.id_practica == id_practica)
    if estado:
        q = q.where(Evaluacion.estado == estado)
    return [resumen(ev) for ev in db.scalars(q).all()]


@router.post("/evaluaciones", response_model=EvaluacionDetalle, status_code=status.HTTP_201_CREATED)
def crear(body: EvaluacionCreate, db: Session = Depends(get_db), user: Usuario = Depends(solo_tutor)):
    ev = Evaluacion(**body.model_dump(), id_tutor=user.id, estado="BORRADOR")
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return detalle(ev)


@router.get("/evaluaciones/{id_evaluacion}", response_model=EvaluacionDetalle)
def obtener(ev: Evaluacion = Depends(evaluacion_del_tutor)):
    return detalle(ev)


@router.patch("/evaluaciones/{id_evaluacion}", response_model=EvaluacionDetalle)
def editar(body: EvaluacionPatch, ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    if ev.estado == "CERRADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación está cerrada.")
    cambios = body.model_dump(exclude_unset=True)
    if ev.intentos and {"nota_maxima", "intentos_permitidos"} & cambios.keys():
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay intentos: no se puede cambiar la nota máxima ni los intentos.")
    for k, v in cambios.items():
        setattr(ev, k, v)
    db.commit()
    db.refresh(ev)
    return detalle(ev)


@router.delete("/evaluaciones/{id_evaluacion}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    if ev.intentos:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya hay intentos presentados; en lugar de eliminarla, ciérrala.")
    db.delete(ev)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/evaluaciones/{id_evaluacion}/publicar", response_model=EvaluacionDetalle)
def publicar(ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    """Asigna la evaluación al estudiante. Solo las preguntas APROBADAS serán visibles."""
    if ev.estado == "CERRADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación está cerrada.")
    if not any(p.estado_revision == "APROBADA" for p in ev.preguntas):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Aprueba al menos una pregunta antes de publicar.")
    ev.estado = "PUBLICADA"
    db.commit()
    db.refresh(ev)
    return detalle(ev)


@router.post("/evaluaciones/{id_evaluacion}/despublicar", response_model=EvaluacionDetalle)
def despublicar(ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    if ev.intentos:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay intentos presentados; ciérrala en su lugar.")
    if ev.estado == "CERRADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación está cerrada.")
    ev.estado = "BORRADOR"
    db.commit()
    db.refresh(ev)
    return detalle(ev)


@router.post("/evaluaciones/{id_evaluacion}/cerrar", response_model=EvaluacionDetalle)
def cerrar(ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    """Cierra la evaluación y envía automáticamente los intentos que sigan en curso."""
    for intento in ev.intentos:
        if intento.estado == "EN_CURSO":
            finalizar_intento(ev, intento)
    ev.estado = "CERRADA"
    actualizar_nota_final(ev)
    db.commit()
    db.refresh(ev)
    return detalle(ev)
