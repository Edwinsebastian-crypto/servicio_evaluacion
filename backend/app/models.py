"""Modelos SQLAlchemy. Reflejan db/schema.sql (que es la fuente de verdad en producción)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# BIGSERIAL en Postgres; INTEGER en SQLite (necesario para autoincrement en tests).
BigInt = BigInteger().with_variant(Integer, "sqlite")
Json = JSON().with_variant(JSONB, "postgresql")


def nota(precision: int = 5):
    # asdecimal=False -> float; así el JSON que ve el frontend son números, no strings.
    return Numeric(precision, 2, asdecimal=False)


class Evaluacion(Base):
    __tablename__ = "evaluacion"

    id_evaluacion: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_practica: Mapped[str] = mapped_column(String(30), index=True)
    id_actividad: Mapped[str | None] = mapped_column(String(30))
    id_tutor: Mapped[str] = mapped_column(String(30), index=True)
    id_estudiante: Mapped[str] = mapped_column(String(30))
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(10), default="BORRADOR", server_default="BORRADOR")
    fecha_evaluacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_limite: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos_permitidos: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    nota_maxima: Mapped[float] = mapped_column(nota(), default=5.0, server_default="5.00")
    mostrar_resultados: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nota_final: Mapped[float | None] = mapped_column(nota())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    preguntas: Mapped[list["Pregunta"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan", passive_deletes=True,
        order_by="(Pregunta.orden, Pregunta.id_pregunta)",
    )
    intentos: Mapped[list["IntentoEvaluacion"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan", passive_deletes=True,
        order_by="IntentoEvaluacion.id_intento",
    )
    generaciones: Mapped[list["GeneracionIA"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan", passive_deletes=True,
        order_by="GeneracionIA.id_generacion.desc()",
    )
    contextos: Mapped[list["ContextoPregunta"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan", passive_deletes=True,
    )


class GeneracionIA(Base):
    __tablename__ = "generacion_ia"

    id_generacion: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_evaluacion: Mapped[int] = mapped_column(
        BigInt, ForeignKey("evaluacion.id_evaluacion", ondelete="CASCADE"), index=True
    )
    id_tutor: Mapped[str] = mapped_column(String(30))
    cantidad_solicitada: Mapped[int] = mapped_column(SmallInteger)
    cantidad_generada: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    parametros: Mapped[dict] = mapped_column(Json, default=dict)
    proveedor: Mapped[str | None] = mapped_column(String(30))
    modelo: Mapped[str | None] = mapped_column(String(80))
    prompt_usado: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(10), default="PENDIENTE", server_default="PENDIENTE")
    error: Mapped[str | None] = mapped_column(Text)
    tokens_entrada: Mapped[int | None] = mapped_column(Integer)
    tokens_salida: Mapped[int | None] = mapped_column(Integer)
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    evaluacion: Mapped[Evaluacion] = relationship(back_populates="generaciones")


class Pregunta(Base):
    __tablename__ = "pregunta"

    id_pregunta: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_evaluacion: Mapped[int] = mapped_column(
        BigInt, ForeignKey("evaluacion.id_evaluacion", ondelete="CASCADE"), index=True
    )
    id_generacion: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("generacion_ia.id_generacion", ondelete="SET NULL")
    )
    tipo_pregunta: Mapped[str] = mapped_column(String(20))
    enunciado: Mapped[str] = mapped_column(Text)
    valor_pregunta: Mapped[float] = mapped_column(nota(6), default=1, server_default="1")
    orden: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    origen: Mapped[str] = mapped_column(String(6), default="MANUAL", server_default="MANUAL")
    estado_revision: Mapped[str] = mapped_column(String(10), default="APROBADA", server_default="APROBADA")
    dificultad: Mapped[str | None] = mapped_column(String(10))
    respuesta_esperada: Mapped[str | None] = mapped_column(Text)
    explicacion: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evaluacion: Mapped[Evaluacion] = relationship(back_populates="preguntas")
    opciones: Mapped[list["OpcionPregunta"]] = relationship(
        back_populates="pregunta", cascade="all, delete-orphan", passive_deletes=True,
        order_by="(OpcionPregunta.orden, OpcionPregunta.id_opcion)",
    )


class OpcionPregunta(Base):
    __tablename__ = "opcion_pregunta"

    id_opcion: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_pregunta: Mapped[int] = mapped_column(
        BigInt, ForeignKey("pregunta.id_pregunta", ondelete="CASCADE"), index=True
    )
    texto: Mapped[str] = mapped_column(Text)
    es_correcta: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    orden: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    pregunta: Mapped[Pregunta] = relationship(back_populates="opciones")


class ContextoPregunta(Base):
    __tablename__ = "contexto_pregunta"

    id_contexto: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_evaluacion: Mapped[int] = mapped_column(
        BigInt, ForeignKey("evaluacion.id_evaluacion", ondelete="CASCADE"), index=True
    )
    id_generacion: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("generacion_ia.id_generacion", ondelete="CASCADE")
    )
    tipo_fuente: Mapped[str] = mapped_column(String(20))
    id_referencia_externa: Mapped[str | None] = mapped_column(String(100))
    nombre: Mapped[str | None] = mapped_column(String(255))
    texto_extraido: Mapped[str | None] = mapped_column(Text)
    caracteres: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    truncado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    evaluacion: Mapped[Evaluacion] = relationship(back_populates="contextos")


class IntentoEvaluacion(Base):
    __tablename__ = "intento_evaluacion"
    __table_args__ = (UniqueConstraint("id_evaluacion", "id_estudiante", "numero_intento"),)

    id_intento: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_evaluacion: Mapped[int] = mapped_column(
        BigInt, ForeignKey("evaluacion.id_evaluacion", ondelete="CASCADE"), index=True
    )
    id_estudiante: Mapped[str] = mapped_column(String(30), index=True)
    numero_intento: Mapped[int] = mapped_column(SmallInteger)
    estado: Mapped[str] = mapped_column(String(10), default="EN_CURSO", server_default="EN_CURSO")
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nota_obtenida: Mapped[float | None] = mapped_column(nota())

    evaluacion: Mapped[Evaluacion] = relationship(back_populates="intentos")
    respuestas: Mapped[list["Respuesta"]] = relationship(
        back_populates="intento", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Respuesta.id_respuesta",
    )


class Respuesta(Base):
    __tablename__ = "respuesta"
    __table_args__ = (UniqueConstraint("id_intento", "id_pregunta"),)

    id_respuesta: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_intento: Mapped[int] = mapped_column(
        BigInt, ForeignKey("intento_evaluacion.id_intento", ondelete="CASCADE"), index=True
    )
    id_pregunta: Mapped[int] = mapped_column(
        BigInt, ForeignKey("pregunta.id_pregunta", ondelete="CASCADE"), index=True
    )
    id_opcion: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("opcion_pregunta.id_opcion", ondelete="SET NULL")
    )
    respuesta: Mapped[str | None] = mapped_column(Text)
    es_correcta: Mapped[bool | None] = mapped_column(Boolean)
    nota_obtenida: Mapped[float | None] = mapped_column(nota(6))
    calificada_por: Mapped[str | None] = mapped_column(String(5))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    intento: Mapped[IntentoEvaluacion] = relationship(back_populates="respuestas")
    pregunta: Mapped[Pregunta] = relationship()
    retros: Mapped[list["RetroPregunta"]] = relationship(
        back_populates="respuesta", cascade="all, delete-orphan", passive_deletes=True,
        order_by="RetroPregunta.id_retro_pregunta",
    )


class RetroPregunta(Base):
    __tablename__ = "retro_pregunta"

    id_retro_pregunta: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    id_respuesta: Mapped[int] = mapped_column(
        BigInt, ForeignKey("respuesta.id_respuesta", ondelete="CASCADE"), index=True
    )
    id_tutor: Mapped[str] = mapped_column(String(30))
    comentario: Mapped[str] = mapped_column(Text)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    respuesta: Mapped[Respuesta] = relationship(back_populates="retros")
