"""Estudiante · ver evaluaciones asignadas, presentarlas y consultar resultados."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import intento_del_estudiante
from ..models import Evaluacion, IntentoEvaluacion, OpcionPregunta, Respuesta
from ..schemas import EvaluacionEstudiante, IntentoEstudiante, RespuestaIn
from ..security import Usuario, solo_estudiante
from ..serializers import intento_estudiante
from ..services.calificacion import aprobadas_de, finalizar_intento, vencida

router = APIRouter(prefix="/estudiante", tags=["Estudiante"])


def _cerrar_si_corresponde(db: Session, intento: IntentoEvaluacion) -> None:
    """Si el intento sigue abierto pero la evaluación se cerró o venció, se envía lo que haya."""
    ev = intento.evaluacion
    if intento.estado == "EN_CURSO" and (ev.estado == "CERRADA" or vencida(ev)):
        finalizar_intento(ev, intento)
        db.commit()
        db.refresh(intento)


def _tarjeta(ev: Evaluacion, mios: list[IntentoEvaluacion]) -> EvaluacionEstudiante:
    abierto = next((i for i in mios if i.estado == "EN_CURSO"), None)
    total = len(aprobadas_de(ev))
    puede = (
        ev.estado == "PUBLICADA" and total > 0 and not vencida(ev)
        and (abierto is not None or len(mios) < ev.intentos_permitidos)
    )
    ultimo = mios[-1] if mios else None
    return EvaluacionEstudiante(
        id_evaluacion=ev.id_evaluacion, id_practica=ev.id_practica, titulo=ev.titulo, descripcion=ev.descripcion,
        estado=ev.estado, fecha_limite=ev.fecha_limite, intentos_permitidos=ev.intentos_permitidos,
        intentos_usados=len(mios), nota_maxima=ev.nota_maxima,
        nota_final=ev.nota_final if any(i.estado == "CALIFICADO" for i in mios) else None,
        total_preguntas=total, id_intento_abierto=abierto.id_intento if abierto else None,
        id_ultimo_intento=ultimo.id_intento if ultimo else None,
        ultimo_intento_estado=ultimo.estado if ultimo else None, puede_intentar=puede,
    )


@router.get("/evaluaciones", response_model=list[EvaluacionEstudiante])
def mis_evaluaciones(db: Session = Depends(get_db), user: Usuario = Depends(solo_estudiante)):
    evs = db.scalars(
        select(Evaluacion)
        .where(Evaluacion.id_estudiante == user.id, Evaluacion.estado.in_(("PUBLICADA", "CERRADA")))
        .options(selectinload(Evaluacion.preguntas), selectinload(Evaluacion.intentos))
        .order_by(Evaluacion.id_evaluacion.desc())
    ).all()
    out = []
    for ev in evs:
        mios = [i for i in ev.intentos if i.id_estudiante == user.id]
        for i in mios:
            _cerrar_si_corresponde(db, i)
        out.append(_tarjeta(ev, mios))
    return out


@router.post("/evaluaciones/{id_evaluacion}/intentos", response_model=IntentoEstudiante)
def iniciar_o_continuar(id_evaluacion: int, db: Session = Depends(get_db), user: Usuario = Depends(solo_estudiante)):
    ev = db.get(Evaluacion, id_evaluacion)
    if ev is None or ev.id_estudiante != user.id or ev.estado == "BORRADOR":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La evaluación no existe.")
    mios = [i for i in ev.intentos if i.id_estudiante == user.id]

    abierto = next((i for i in mios if i.estado == "EN_CURSO"), None)
    if abierto is not None:
        _cerrar_si_corresponde(db, abierto)
        return intento_estudiante(abierto)

    if ev.estado != "PUBLICADA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación está cerrada.")
    if vencida(ev):
        raise HTTPException(status.HTTP_409_CONFLICT, "La fecha límite de la evaluación ya venció.")
    if len(mios) >= ev.intentos_permitidos:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya usaste todos los intentos permitidos.")
    if not aprobadas_de(ev):
        raise HTTPException(status.HTTP_409_CONFLICT, "La evaluación aún no tiene preguntas.")

    intento = IntentoEvaluacion(id_evaluacion=ev.id_evaluacion, id_estudiante=user.id,
                                numero_intento=len(mios) + 1, estado="EN_CURSO")
    db.add(intento)
    db.commit()
    db.refresh(intento)
    return intento_estudiante(intento)


@router.get("/intentos/{id_intento}", response_model=IntentoEstudiante)
def ver_intento(intento: IntentoEvaluacion = Depends(intento_del_estudiante), db: Session = Depends(get_db)):
    _cerrar_si_corresponde(db, intento)
    return intento_estudiante(intento)


@router.put("/intentos/{id_intento}/respuestas/{id_pregunta}")
def guardar_respuesta(id_pregunta: int, body: RespuestaIn, intento: IntentoEvaluacion = Depends(intento_del_estudiante),
                      db: Session = Depends(get_db)):
    """Autoguardado de una respuesta (se puede llamar muchas veces). No califica."""
    ev = intento.evaluacion
    _cerrar_si_corresponde(db, intento)
    if intento.estado != "EN_CURSO":
        raise HTTPException(status.HTTP_409_CONFLICT, "Este intento ya fue enviado o la evaluación se cerró.")

    pregunta = next((p for p in aprobadas_de(ev) if p.id_pregunta == id_pregunta), None)
    if pregunta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La pregunta no pertenece a esta evaluación.")

    r = next((x for x in intento.respuestas if x.id_pregunta == id_pregunta), None)
    if r is None:
        r = Respuesta(id_intento=intento.id_intento, id_pregunta=id_pregunta)
        db.add(r)

    if pregunta.tipo_pregunta == "ABIERTA":
        r.id_opcion, r.respuesta = None, (body.respuesta or "")
    else:
        if body.id_opcion is None:
            r.id_opcion, r.respuesta = None, None
        else:
            op = next((o for o in pregunta.opciones if o.id_opcion == body.id_opcion), None)
            if op is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La opción no pertenece a la pregunta.")
            r.id_opcion, r.respuesta = op.id_opcion, op.texto
    db.commit()
    return {"guardado": True}


@router.post("/intentos/{id_intento}/enviar", response_model=IntentoEstudiante)
def enviar(intento: IntentoEvaluacion = Depends(intento_del_estudiante), db: Session = Depends(get_db)):
    if intento.estado != "EN_CURSO":
        raise HTTPException(status.HTTP_409_CONFLICT, "Este intento ya fue enviado.")
    ev = intento.evaluacion
    if ev.estado == "CERRADA" or vencida(ev):
        _cerrar_si_corresponde(db, intento)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "La evaluación se cerró o venció; se enviaron las respuestas que alcanzaste a guardar.")
    finalizar_intento(ev, intento)
    db.commit()
    db.refresh(intento)
    return intento_estudiante(intento)
