"""Director · consulta de solo lectura (cifras, alertas y detalle de las evaluaciones).

Solo hay GET: el director NO crea, edita, publica ni califica. Tampoco ve lo que escribió cada
estudiante: únicamente cifras agregadas, el análisis por pregunta y las notas de los intentos.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Evaluacion, IntentoEvaluacion, Pregunta, Respuesta
from ..schemas import EvaluacionDetalle, IntentoDetalleTutor, IntentoResumenTutor
from ..schemas_director import DetalleDirector, ListaDirector, ResumenDirector
from ..security import Usuario, solo_director
from ..serializers import detalle as detalle_serializer, intento_detalle_tutor, intento_resumen_tutor
from ..services import estadisticas as est

router = APIRouter(prefix="/director", tags=["Director · Solo lectura"])

_CARGA = (selectinload(Evaluacion.preguntas), selectinload(Evaluacion.intentos),
          selectinload(Evaluacion.generaciones))


def _todas(db: Session) -> list[Evaluacion]:
    return list(db.scalars(select(Evaluacion).options(*_CARGA).order_by(Evaluacion.id_evaluacion)))


@router.get("/resumen", response_model=ResumenDirector)
def resumen(db: Session = Depends(get_db), _: Usuario = Depends(solo_director)):
    return est.resumen_global(_todas(db), est.ahora_utc())


@router.get("/evaluaciones", response_model=ListaDirector)
def listar(
    estado: str | None = Query(default=None, pattern="^(BORRADOR|PUBLICADA|CERRADA)$"),
    id_tutor: str | None = Query(default=None, max_length=30),
    id_practica: str | None = Query(default=None, max_length=30),
    q: str | None = Query(default=None, max_length=100),
    solo_alertas: bool = False,
    limite: int = Query(default=25, ge=1, le=100),
    desplazamiento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(solo_director),
):
    consulta = select(Evaluacion).options(*_CARGA)
    if estado:
        consulta = consulta.where(Evaluacion.estado == estado)
    if id_tutor:
        consulta = consulta.where(Evaluacion.id_tutor == id_tutor)
    if id_practica:
        consulta = consulta.where(Evaluacion.id_practica == id_practica)
    if q and q.strip():
        consulta = consulta.where(func.lower(Evaluacion.titulo).like(f"%{q.strip().lower()}%"))
    consulta = consulta.order_by(Evaluacion.fecha_evaluacion.desc(), Evaluacion.id_evaluacion.desc())

    ahora = est.ahora_utc()
    filas = est.filtrar_lista([est.resumen_evaluacion(ev, ahora) for ev in db.scalars(consulta)], solo_alertas)
    return {"total": len(filas), "limite": limite, "desplazamiento": desplazamiento,
            "items": filas[desplazamiento:desplazamiento + limite]}


@router.get("/evaluaciones/{id_evaluacion}", response_model=DetalleDirector)
def detalle(id_evaluacion: int, db: Session = Depends(get_db), _: Usuario = Depends(solo_director)):
    ev = db.scalars(select(Evaluacion).options(*_CARGA).where(Evaluacion.id_evaluacion == id_evaluacion)).first()
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La evaluación no existe.")
    ahora = est.ahora_utc()
    return {
        **est.resumen_evaluacion(ev, ahora),
        "descripcion": ev.descripcion, "mostrar_resultados": ev.mostrar_resultados,
        "preguntas": est.analisis_preguntas(ev), "intentos": est.intentos_de(ev, ahora),
        "generaciones": est.generaciones_de(ev),
    }


@router.get("/evaluaciones/{id_evaluacion}/preguntas", response_model=EvaluacionDetalle)
def detalle_preguntas(id_evaluacion: int, db: Session = Depends(get_db), _: Usuario = Depends(solo_director)):
    """Consulta de solo lectura de todas las preguntas de la evaluación (con opciones y criterios)."""
    ev = db.scalars(
        select(Evaluacion)
        .options(
            selectinload(Evaluacion.preguntas).selectinload(Pregunta.opciones),
            selectinload(Evaluacion.intentos),
            selectinload(Evaluacion.generaciones),
            selectinload(Evaluacion.contextos),
        )
        .where(Evaluacion.id_evaluacion == id_evaluacion)
    ).first()
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La evaluación no existe.")
    return detalle_serializer(ev)


@router.get("/evaluaciones/{id_evaluacion}/intentos", response_model=list[IntentoResumenTutor])
def listar_intentos(id_evaluacion: int, db: Session = Depends(get_db), _: Usuario = Depends(solo_director)):
    """Consulta de los intentos presentados o en curso para la evaluación."""
    ev = db.scalars(
        select(Evaluacion)
        .options(
            selectinload(Evaluacion.preguntas),
            selectinload(Evaluacion.intentos).selectinload(IntentoEvaluacion.respuestas),
        )
        .where(Evaluacion.id_evaluacion == id_evaluacion)
    ).first()
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La evaluación no existe.")
    return [intento_resumen_tutor(i) for i in ev.intentos]


@router.get("/intentos/{id_intento}", response_model=IntentoDetalleTutor)
def ver_intento(id_intento: int, db: Session = Depends(get_db), _: Usuario = Depends(solo_director)):
    """Consulta de las respuestas que el estudiante colocó en un intento, notas y retroalimentación."""
    i = db.scalars(
        select(IntentoEvaluacion)
        .options(
            selectinload(IntentoEvaluacion.evaluacion).selectinload(Evaluacion.preguntas).selectinload(Pregunta.opciones),
            selectinload(IntentoEvaluacion.respuestas).selectinload(Respuesta.retros),
            selectinload(IntentoEvaluacion.respuestas).selectinload(Respuesta.pregunta),
        )
        .where(IntentoEvaluacion.id_intento == id_intento)
    ).first()
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El intento no existe.")
    return intento_detalle_tutor(i)
