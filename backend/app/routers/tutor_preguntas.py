"""Tutor · crear manualmente, editar, revisar (aprobar/rechazar) y ordenar preguntas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import asegurar_editable, evaluacion_del_tutor, pregunta_del_tutor
from ..models import Evaluacion, OpcionPregunta, Pregunta
from ..schemas import OpcionIn, PreguntaIn, PreguntaOut, PreguntaPatch, ReordenarIn
from ..services.validacion import validar_estructura

router = APIRouter(prefix="/tutor", tags=["Tutor · Preguntas"])


def _poner_opciones(db: Session, p: Pregunta, opciones: list[OpcionIn]) -> None:
    """Reemplaza las opciones. Se hace en dos pasos (borrar y luego insertar) porque la BD
    garantiza una sola opción correcta por pregunta con un índice único."""
    p.opciones.clear()
    db.flush()
    for n, o in enumerate(opciones, 1):
        p.opciones.append(OpcionPregunta(texto=o.texto.strip(), es_correcta=o.es_correcta, orden=n))


@router.post("/evaluaciones/{id_evaluacion}/preguntas", response_model=PreguntaOut,
             status_code=status.HTTP_201_CREATED)
def crear_manual(body: PreguntaIn, ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    asegurar_editable(ev)
    orden = max((p.orden for p in ev.preguntas), default=0) + 1
    p = Pregunta(
        id_evaluacion=ev.id_evaluacion, tipo_pregunta=body.tipo_pregunta, enunciado=body.enunciado.strip(),
        valor_pregunta=body.valor_pregunta, dificultad=body.dificultad,
        respuesta_esperada=(body.respuesta_esperada or None) if body.tipo_pregunta == "ABIERTA" else None,
        explicacion=body.explicacion or None, orden=orden, origen="MANUAL", estado_revision="APROBADA",
    )
    db.add(p)
    db.flush()
    _poner_opciones(db, p, body.opciones)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/preguntas/{id_pregunta}", response_model=PreguntaOut)
def editar(body: PreguntaPatch, p: Pregunta = Depends(pregunta_del_tutor), db: Session = Depends(get_db)):
    asegurar_editable(p.evaluacion)
    cambios = body.model_dump(exclude_unset=True)
    opciones = body.opciones if "opciones" in cambios else None
    cambios.pop("opciones", None)

    tipo = cambios.get("tipo_pregunta", p.tipo_pregunta)
    finales = ([(o.texto, o.es_correcta) for o in opciones] if opciones is not None
               else [(o.texto, o.es_correcta) for o in p.opciones])
    if tipo == "ABIERTA" and opciones is None and p.tipo_pregunta != "ABIERTA":
        finales = []          # al pasar a abierta se descartan las opciones
        opciones = []
    try:
        validar_estructura(tipo, finales)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    for k, v in cambios.items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    if tipo != "ABIERTA":
        p.respuesta_esperada = None
    if opciones is not None:
        _poner_opciones(db, p, opciones)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/preguntas/{id_pregunta}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(p: Pregunta = Depends(pregunta_del_tutor), db: Session = Depends(get_db)):
    asegurar_editable(p.evaluacion)
    db.delete(p)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _revision(p: Pregunta, estado: str, db: Session) -> Pregunta:
    asegurar_editable(p.evaluacion)
    p.estado_revision = estado
    db.commit()
    db.refresh(p)
    return p


@router.post("/preguntas/{id_pregunta}/aprobar", response_model=PreguntaOut)
def aprobar(p: Pregunta = Depends(pregunta_del_tutor), db: Session = Depends(get_db)):
    return _revision(p, "APROBADA", db)


@router.post("/preguntas/{id_pregunta}/rechazar", response_model=PreguntaOut)
def rechazar(p: Pregunta = Depends(pregunta_del_tutor), db: Session = Depends(get_db)):
    return _revision(p, "RECHAZADA", db)


@router.post("/evaluaciones/{id_evaluacion}/preguntas/aprobar-todas")
def aprobar_todas(ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    asegurar_editable(ev)
    n = 0
    for p in ev.preguntas:
        if p.estado_revision == "BORRADOR":
            p.estado_revision = "APROBADA"
            n += 1
    db.commit()
    return {"aprobadas": n}


@router.put("/evaluaciones/{id_evaluacion}/preguntas/orden", response_model=list[PreguntaOut])
def reordenar(body: ReordenarIn, ev: Evaluacion = Depends(evaluacion_del_tutor), db: Session = Depends(get_db)):
    asegurar_editable(ev)
    por_id = {p.id_pregunta: p for p in ev.preguntas}
    if set(body.ids_en_orden) != set(por_id) or len(body.ids_en_orden) != len(por_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "ids_en_orden debe contener exactamente todas las preguntas de la evaluación.")
    for n, pid in enumerate(body.ids_en_orden, 1):
        por_id[pid].orden = n
    db.commit()
    db.refresh(ev)
    return ev.preguntas
