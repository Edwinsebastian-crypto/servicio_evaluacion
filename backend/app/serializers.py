"""Conversión de objetos ORM a los esquemas de la API."""
from __future__ import annotations

from .models import Evaluacion, IntentoEvaluacion, Pregunta
from .schemas import (
    ContextoOut, EvaluacionDetalle, EvaluacionResumen, GeneracionResumen, IntentoEstudiante, IntentoResumenTutor, OpcionEstudiante,
    PreguntaEstudiante, PreguntaOut, RespuestaEstudiante, RespuestaTutor, IntentoDetalleTutor,
)
from .services.calificacion import aprobadas_de, pregunta_pendiente


def resumen(ev: Evaluacion) -> EvaluacionResumen:
    pend = sum(1 for p in ev.preguntas if p.estado_revision == "BORRADOR")
    apro = sum(1 for p in ev.preguntas if p.estado_revision == "APROBADA")
    base = {c: getattr(ev, c) for c in EvaluacionResumen.model_fields
            if c not in ("total_preguntas", "preguntas_aprobadas", "preguntas_pendientes", "intentos_presentados")}
    return EvaluacionResumen(
        **base, total_preguntas=len(ev.preguntas), preguntas_aprobadas=apro,
        preguntas_pendientes=pend, intentos_presentados=len(ev.intentos),
    )


def detalle(ev: Evaluacion) -> EvaluacionDetalle:
    r = resumen(ev)
    return EvaluacionDetalle(
        **r.model_dump(),
        preguntas=[PreguntaOut.model_validate(p) for p in ev.preguntas],
        generaciones=[GeneracionResumen.model_validate(g) for g in ev.generaciones],
        contextos=[ContextoOut.model_validate(c) for c in ev.contextos],
    )


# ---------------------------------------------------------------- estudiante
def _pregunta_estudiante(p: Pregunta, revelar: bool) -> PreguntaEstudiante:
    return PreguntaEstudiante(
        id_pregunta=p.id_pregunta, tipo_pregunta=p.tipo_pregunta, enunciado=p.enunciado,
        valor_pregunta=p.valor_pregunta, orden=p.orden,
        opciones=[OpcionEstudiante(id_opcion=o.id_opcion, texto=o.texto, orden=o.orden,
                                   es_correcta=o.es_correcta if revelar else None) for o in p.opciones],
        explicacion=p.explicacion if revelar else None,
        respuesta_esperada=p.respuesta_esperada if (revelar and p.tipo_pregunta == "ABIERTA") else None,
    )


def intento_estudiante(i: IntentoEvaluacion) -> IntentoEstudiante:
    ev = i.evaluacion
    cerrado = i.estado != "EN_CURSO"
    revelar = cerrado and ev.mostrar_resultados
    aprobadas = aprobadas_de(ev)
    por_pregunta = {r.id_pregunta: r for r in i.respuestas}

    respuestas = []
    for p in aprobadas:
        r = por_pregunta.get(p.id_pregunta)
        if r is None:
            continue
        respuestas.append(RespuestaEstudiante(
            id_pregunta=p.id_pregunta, id_opcion=r.id_opcion, respuesta=r.respuesta,
            es_correcta=r.es_correcta if revelar else None,
            nota_obtenida=r.nota_obtenida if revelar else None,
            pendiente_revision=cerrado and pregunta_pendiente(p, r),
            retroalimentacion=[x.comentario for x in r.retros] if cerrado else [],
        ))
    return IntentoEstudiante(
        id_intento=i.id_intento, id_evaluacion=ev.id_evaluacion, titulo=ev.titulo,
        numero_intento=i.numero_intento, estado=i.estado, fecha_inicio=i.fecha_inicio,
        fecha_envio=i.fecha_envio,
        nota_obtenida=i.nota_obtenida if i.estado == "CALIFICADO" else None,
        nota_maxima=ev.nota_maxima, resultados_visibles=revelar,
        preguntas=[_pregunta_estudiante(p, revelar) for p in aprobadas], respuestas=respuestas,
    )


# --------------------------------------------------------------------- tutor
def intento_resumen_tutor(i: IntentoEvaluacion) -> IntentoResumenTutor:
    aprobadas = aprobadas_de(i.evaluacion)
    por_pregunta = {r.id_pregunta: r for r in i.respuestas}
    pend = sum(1 for p in aprobadas if i.estado != "EN_CURSO" and pregunta_pendiente(p, por_pregunta.get(p.id_pregunta)))
    return IntentoResumenTutor(
        id_intento=i.id_intento, id_estudiante=i.id_estudiante, numero_intento=i.numero_intento,
        estado=i.estado, fecha_inicio=i.fecha_inicio, fecha_envio=i.fecha_envio,
        nota_obtenida=i.nota_obtenida, respuestas_pendientes=pend,
    )


def intento_detalle_tutor(i: IntentoEvaluacion) -> IntentoDetalleTutor:
    ev = i.evaluacion
    por_pregunta = {r.id_pregunta: r for r in i.respuestas}
    filas = []
    for p in aprobadas_de(ev):
        r = por_pregunta.get(p.id_pregunta)
        correcta = next((o.texto for o in p.opciones if o.es_correcta), None)
        filas.append(RespuestaTutor(
            id_respuesta=r.id_respuesta if r else None, id_pregunta=p.id_pregunta,
            tipo_pregunta=p.tipo_pregunta, enunciado=p.enunciado, valor_pregunta=p.valor_pregunta,
            respuesta=r.respuesta if r else None, id_opcion=r.id_opcion if r else None,
            opcion_correcta=correcta, respuesta_esperada=p.respuesta_esperada,
            es_correcta=r.es_correcta if r else None, nota_obtenida=r.nota_obtenida if r else None,
            calificada_por=r.calificada_por if r else None,
            pendiente=bool(r) and i.estado != "EN_CURSO" and pregunta_pendiente(p, r),
            retros=[{"id_retro_pregunta": x.id_retro_pregunta, "comentario": x.comentario, "fecha": x.fecha}
                    for x in (r.retros if r else [])],
        ))
    base = intento_resumen_tutor(i)
    return IntentoDetalleTutor(**base.model_dump(), nota_maxima=ev.nota_maxima, respuestas=filas)
