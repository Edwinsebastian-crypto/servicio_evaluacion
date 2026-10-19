"""Esquemas Pydantic de entrada y salida de la API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .services.validacion import validar_estructura

Tipo = Literal["OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA"]
Dificultad = Literal["FACIL", "MEDIA", "DIFICIL"]
EstadoEval = Literal["BORRADOR", "PUBLICADA", "CERRADA"]
TipoFuente = Literal["TEMA_LIBRE", "EVIDENCIA", "ARCHIVO_EVIDENCIA", "ACTIVIDAD", "ARCHIVO_ACTIVIDAD"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------------
#  Preguntas y opciones
# ----------------------------------------------------------------------------
class OpcionIn(BaseModel):
    texto: str = Field(min_length=1, max_length=1000)
    es_correcta: bool = False


class OpcionOut(ORM):
    id_opcion: int
    texto: str
    es_correcta: bool
    orden: int


class PreguntaIn(BaseModel):
    tipo_pregunta: Tipo
    enunciado: str = Field(min_length=3, max_length=4000)
    valor_pregunta: float = Field(default=1, gt=0, le=100)
    dificultad: Dificultad | None = None
    respuesta_esperada: str | None = Field(default=None, max_length=4000)
    explicacion: str | None = Field(default=None, max_length=4000)
    opciones: list[OpcionIn] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _estructura(self):
        try:
            validar_estructura(self.tipo_pregunta, [(o.texto, o.es_correcta) for o in self.opciones])
        except ValueError as e:
            raise ValueError(str(e))
        return self


class PreguntaPatch(BaseModel):
    """Edición parcial. Si se envía `opciones`, REEMPLAZA todas las existentes."""
    tipo_pregunta: Tipo | None = None
    enunciado: str | None = Field(default=None, min_length=3, max_length=4000)
    valor_pregunta: float | None = Field(default=None, gt=0, le=100)
    dificultad: Dificultad | None = None
    respuesta_esperada: str | None = Field(default=None, max_length=4000)
    explicacion: str | None = Field(default=None, max_length=4000)
    opciones: list[OpcionIn] | None = Field(default=None, max_length=6)


class PreguntaOut(ORM):
    id_pregunta: int
    id_evaluacion: int
    id_generacion: int | None
    tipo_pregunta: Tipo
    enunciado: str
    valor_pregunta: float
    orden: int
    origen: Literal["MANUAL", "IA"]
    estado_revision: Literal["BORRADOR", "APROBADA", "RECHAZADA"]
    dificultad: Dificultad | None
    respuesta_esperada: str | None
    explicacion: str | None
    opciones: list[OpcionOut]


class ReordenarIn(BaseModel):
    ids_en_orden: list[int] = Field(min_length=1)


# ----------------------------------------------------------------------------
#  Evaluaciones
# ----------------------------------------------------------------------------
class EvaluacionCreate(BaseModel):
    id_practica: str = Field(min_length=1, max_length=30)
    id_estudiante: str = Field(min_length=1, max_length=30)
    id_actividad: str | None = Field(default=None, max_length=30)
    titulo: str = Field(min_length=3, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    fecha_limite: datetime | None = None
    intentos_permitidos: int = Field(default=1, ge=1, le=10)
    nota_maxima: float = Field(default=5.0, gt=0, le=100)
    mostrar_resultados: bool = True

    @field_validator("titulo")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class EvaluacionPatch(BaseModel):
    titulo: str | None = Field(default=None, min_length=3, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    id_actividad: str | None = Field(default=None, max_length=30)
    fecha_limite: datetime | None = None
    intentos_permitidos: int | None = Field(default=None, ge=1, le=10)
    nota_maxima: float | None = Field(default=None, gt=0, le=100)
    mostrar_resultados: bool | None = None


class EvaluacionResumen(BaseModel):
    id_evaluacion: int
    id_practica: str
    id_actividad: str | None
    id_tutor: str
    id_estudiante: str
    titulo: str
    descripcion: str | None
    estado: EstadoEval
    fecha_evaluacion: datetime
    fecha_limite: datetime | None
    intentos_permitidos: int
    nota_maxima: float
    mostrar_resultados: bool
    nota_final: float | None
    total_preguntas: int = 0
    preguntas_aprobadas: int = 0
    preguntas_pendientes: int = 0
    intentos_presentados: int = 0


class GeneracionResumen(ORM):
    id_generacion: int
    cantidad_solicitada: int
    cantidad_generada: int
    proveedor: str | None
    modelo: str | None
    estado: str
    error: str | None
    parametros: dict
    created_at: datetime


class ContextoOut(ORM):
    id_contexto: int
    id_generacion: int | None
    tipo_fuente: TipoFuente
    id_referencia_externa: str | None
    nombre: str | None
    caracteres: int
    truncado: bool


class EvaluacionDetalle(EvaluacionResumen):
    preguntas: list[PreguntaOut] = []
    generaciones: list[GeneracionResumen] = []
    contextos: list[ContextoOut] = []


# ----------------------------------------------------------------------------
#  Generación con IA
# ----------------------------------------------------------------------------
class FuenteIn(BaseModel):
    tipo: TipoFuente
    id_referencia: str | None = Field(default=None, max_length=100)
    texto: str | None = Field(default=None, max_length=30000)   # solo TEMA_LIBRE
    nombre: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _requisitos(self):
        if self.tipo == "TEMA_LIBRE":
            if not self.texto or len(self.texto.strip()) < 10:
                raise ValueError("El tema o contexto libre debe tener al menos 10 caracteres.")
        elif not self.id_referencia:
            raise ValueError(f"La fuente {self.tipo} necesita id_referencia.")
        return self


class GenerarIn(BaseModel):
    fuentes: list[FuenteIn] = Field(min_length=1, max_length=10)
    cantidad: int = Field(ge=1, le=30)
    tipos: list[Tipo] = Field(default_factory=lambda: ["OPCION_MULTIPLE"], min_length=1)
    dificultad: Dificultad | Literal["MIXTA"] = "MEDIA"
    instrucciones: str | None = Field(default=None, max_length=1000)
    valor_por_pregunta: float = Field(default=1, gt=0, le=100)

    @field_validator("tipos")
    @classmethod
    def _unicos(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _limite_evidencias(self):
        evs = [f for f in self.fuentes if f.tipo in ("EVIDENCIA", "ARCHIVO_EVIDENCIA")]
        if len(evs) > 3:
            raise ValueError("Puedes seleccionar máximo 3 evidencias como contexto para no sobrecargar la IA.")
        return self


class GeneracionOut(GeneracionResumen):
    advertencias: list[str] = []
    preguntas: list[PreguntaOut] = []


# ----------------------------------------------------------------------------
#  Evidencias (proxy del otro servicio) — para el selector del tutor
# ----------------------------------------------------------------------------
class ArchivoRef(BaseModel):
    id_archivo: str
    nombre: str
    tipo_mime: str | None = None


class EvidenciaRef(BaseModel):
    id_evidencia: str
    descripcion: str | None = None
    horas_realizadas: float | None = None
    id_actividad: str | None = None
    nombre_actividad: str | None = None
    archivos: list[ArchivoRef] = []


# ----------------------------------------------------------------------------
#  Estudiante
# ----------------------------------------------------------------------------
class OpcionEstudiante(BaseModel):
    id_opcion: int
    texto: str
    orden: int
    es_correcta: bool | None = None          # solo se llena al revelar resultados


class PreguntaEstudiante(BaseModel):
    id_pregunta: int
    tipo_pregunta: Tipo
    enunciado: str
    valor_pregunta: float
    orden: int
    opciones: list[OpcionEstudiante]
    explicacion: str | None = None           # solo al revelar
    respuesta_esperada: str | None = None    # solo al revelar


class RespuestaEstudiante(BaseModel):
    id_pregunta: int
    id_opcion: int | None = None
    respuesta: str | None = None
    es_correcta: bool | None = None          # solo al revelar
    nota_obtenida: float | None = None       # solo al revelar
    pendiente_revision: bool = False
    retroalimentacion: list[str] = []


class RespuestaIn(BaseModel):
    id_opcion: int | None = None
    respuesta: str | None = Field(default=None, max_length=10000)


class EvaluacionEstudiante(BaseModel):
    id_evaluacion: int
    id_practica: str
    titulo: str
    descripcion: str | None
    estado: EstadoEval
    fecha_limite: datetime | None
    intentos_permitidos: int
    intentos_usados: int
    nota_maxima: float
    nota_final: float | None
    total_preguntas: int
    id_intento_abierto: int | None = None
    id_ultimo_intento: int | None = None
    ultimo_intento_estado: str | None = None
    puede_intentar: bool = False


class IntentoEstudiante(BaseModel):
    id_intento: int
    id_evaluacion: int
    titulo: str
    numero_intento: int
    estado: Literal["EN_CURSO", "ENVIADO", "CALIFICADO"]
    fecha_inicio: datetime
    fecha_envio: datetime | None
    nota_obtenida: float | None
    nota_maxima: float
    resultados_visibles: bool
    preguntas: list[PreguntaEstudiante]
    respuestas: list[RespuestaEstudiante]


# ----------------------------------------------------------------------------
#  Resultados (tutor)
# ----------------------------------------------------------------------------
class IntentoResumenTutor(BaseModel):
    id_intento: int
    id_estudiante: str
    numero_intento: int
    estado: str
    fecha_inicio: datetime
    fecha_envio: datetime | None
    nota_obtenida: float | None
    respuestas_pendientes: int


class RespuestaTutor(BaseModel):
    id_respuesta: int | None
    id_pregunta: int
    tipo_pregunta: Tipo
    enunciado: str
    valor_pregunta: float
    respuesta: str | None
    id_opcion: int | None
    opcion_correcta: str | None
    respuesta_esperada: str | None
    es_correcta: bool | None
    nota_obtenida: float | None
    calificada_por: str | None
    pendiente: bool
    retros: list[dict]


class IntentoDetalleTutor(IntentoResumenTutor):
    nota_maxima: float
    respuestas: list[RespuestaTutor]


class CalificarIn(BaseModel):
    nota_obtenida: float = Field(ge=0)
    comentario: str | None = Field(default=None, max_length=4000)


class RetroIn(BaseModel):
    comentario: str = Field(min_length=1, max_length=4000)
