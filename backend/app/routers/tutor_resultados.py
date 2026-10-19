"""Tutor · ver intentos de los estudiantes, calificar respuestas abiertas y dar retroalimentación."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import evaluacion_del_tutor, intento_del_tutor, respuesta_del_tutor
from ..models import Evaluacion, IntentoEvaluacion, Respuesta, RetroPregunta
from ..schemas import CalificarIn, IntentoDetalleTutor, IntentoResumenTutor, RetroIn
from ..security import Usuario, solo_tutor
from ..serializers import intento_detalle_tutor, intento_resumen_tutor
from ..services.calificacion import actualizar_nota_final, aprobadas_de, recalcular_intento

router = APIRouter(prefix="/tutor", tags=["Tutor · Resultados"])


@router.get("/evaluaciones/{id_evaluacion}/intentos", response_model=list[IntentoResumenTutor])
def listar_intentos(ev: Evaluacion = Depends(evaluacion_del_tutor)):
    return [intento_resumen_tutor(i) for i in ev.intentos]


@router.get("/intentos/{id_intento}", response_model=IntentoDetalleTutor)
def ver_intento(i: IntentoEvaluacion = Depends(intento_del_tutor)):
    return intento_detalle_tutor(i)


@router.post("/respuestas/{id_respuesta}/calificar", response_model=IntentoDetalleTutor)
def calificar(body: CalificarIn, r: Respuesta = Depends(respuesta_del_tutor), db: Session = Depends(get_db),
              user: Usuario = Depends(solo_tutor)):
    intento = r.intento
    ev = intento.evaluacion
    if intento.estado == "EN_CURSO":
        raise HTTPException(status.HTTP_409_CONFLICT, "El estudiante aún no ha enviado este intento.")
    pregunta = r.pregunta
    if body.nota_obtenida > pregunta.valor_pregunta:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"La nota no puede superar el valor de la pregunta ({pregunta.valor_pregunta}).")
    r.nota_obtenida = body.nota_obtenida
    r.es_correcta = body.nota_obtenida >= pregunta.valor_pregunta * 0.5
    r.calificada_por = "TUTOR"
    if body.comentario and body.comentario.strip():
        db.add(RetroPregunta(id_respuesta=r.id_respuesta, id_tutor=user.id, comentario=body.comentario.strip()))
    db.flush()
    db.refresh(intento)
    recalcular_intento(ev, intento, aprobadas_de(ev))
    actualizar_nota_final(ev)
    db.commit()
    db.refresh(intento)
    return intento_detalle_tutor(intento)


@router.post("/respuestas/{id_respuesta}/retro", response_model=IntentoDetalleTutor,
             status_code=status.HTTP_201_CREATED)
def comentar(body: RetroIn, r: Respuesta = Depends(respuesta_del_tutor), db: Session = Depends(get_db),
             user: Usuario = Depends(solo_tutor)):
    db.add(RetroPregunta(id_respuesta=r.id_respuesta, id_tutor=user.id, comentario=body.comentario.strip()))
    db.commit()
    db.refresh(r.intento)
    return intento_detalle_tutor(r.intento)
