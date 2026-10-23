"""Respuestas de la API del director (solo lectura). Coinciden con los dicts de services/estadisticas.py."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AlertaOut(BaseModel):
    tipo: str                      # REVISION_ATRASADA | VENCIDA_SIN_CERRAR | BORRADOR_ANTIGUO | SIN_INTENTOS
    severidad: str                 # ALTA | MEDIA | BAJA
    cantidad: int | None = None
    dias: int | None = None


class AlertaGlobalOut(AlertaOut):
    id_evaluacion: int
    titulo: str
    id_practica: str
    id_tutor: str


class EvaluacionDirector(BaseModel):
    id_evaluacion: int
    id_practica: str
    id_tutor: str
    id_estudiante: str
    titulo: str
    estado: str
    fecha_evaluacion: datetime
    fecha_limite: datetime | None
    vencida: bool
    intentos_permitidos: int
    nota_maxima: float
    total_preguntas: int
    preguntas_aprobadas: int
    preguntas_ia: int
    intentos_iniciados: int
    intentos_enviados: int
    intentos_calificados: int
    pendientes_revision: int
    espera_max_dias: int | None
    nota_final: float | None
    porcentaje_final: float | None
    alertas: list[AlertaOut]


class ListaDirector(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[EvaluacionDirector]


class PreguntaAnalisis(BaseModel):
    id_pregunta: int
    orden: int
    tipo_pregunta: str
    enunciado: str
    valor_pregunta: float
    origen: str
    estado_revision: str
    dificultad: str | None
    respuestas: int
    correctas: int
    incorrectas: int
    sin_calificar: int
    pct_acierto: float | None


class IntentoDirector(BaseModel):
    id_intento: int
    numero_intento: int
    estado: str
    fecha_inicio: datetime
    fecha_envio: datetime | None
    nota_obtenida: float | None
    porcentaje: float | None
    dias_esperando: int | None


class GeneracionDirector(BaseModel):
    id_generacion: int
    proveedor: str | None
    modelo: str | None
    estado: str
    cantidad_solicitada: int
    cantidad_generada: int
    duracion_ms: int | None
    created_at: datetime


class DetalleDirector(EvaluacionDirector):
    descripcion: str | None
    mostrar_resultados: bool
    preguntas: list[PreguntaAnalisis]
    intentos: list[IntentoDirector]
    generaciones: list[GeneracionDirector]


# ---------------------------------------------------------------- resumen global
class Totales(BaseModel):
    evaluaciones: int
    practicas: int
    tutores: int
    estudiantes: int
    preguntas: int
    intentos_iniciados: int
    intentos_en_curso: int
    intentos_pendientes_revision: int
    intentos_calificados: int
    evaluaciones_vencidas_sin_cerrar: int


class RangoNota(BaseModel):
    desde: int
    hasta: int
    cantidad: int


class Desempeno(BaseModel):
    evaluaciones_calificadas: int
    promedio_pct: float | None
    aprobacion_pct: float | None
    aprobadas: int
    reprobadas: int
    distribucion: list[RangoNota]


class PreguntasResumen(BaseModel):
    por_tipo: dict[str, int]
    por_dificultad: dict[str, int]
    por_origen: dict[str, int]


class IAResumen(BaseModel):
    preguntas: int
    aprobadas: int
    rechazadas: int
    por_revisar: int
    aceptacion_pct: float | None
    uso_pct: float | None
    generaciones: int
    generaciones_fallidas: int
    por_proveedor: dict[str, int]


class MesActividad(BaseModel):
    mes: str
    evaluaciones_creadas: int
    intentos_enviados: int


class TutorResumen(BaseModel):
    id_tutor: str
    evaluaciones: int
    publicadas: int
    intentos_calificados: int
    pendientes_revision: int
    espera_max_dias: int | None
    promedio_pct: float | None
    alertas: int


class ResumenDirector(BaseModel):
    generado_en: datetime
    umbral_aprobacion_pct: float
    dias_revision_atrasada: int
    dias_borrador_antiguo: int
    dias_sin_intentos: int
    totales: Totales
    por_estado: dict[str, int]
    desempeno: Desempeno
    preguntas: PreguntasResumen
    ia: IAResumen
    historial: list[MesActividad]
    por_tutor: list[TutorResumen]
    alertas: list[AlertaGlobalOut]
