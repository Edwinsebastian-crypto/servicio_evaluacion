"""Acceso a las evidencias y actividades de las prácticas.

Siguiendo la arquitectura de microservicios, el servicio de evaluación NUNCA
consulta directamente la base de datos de prácticas (postgres_1) del monolito.
Cada servicio gestiona exclusivamente su propia base de datos (postgres_2).

Para acceder a evidencias, actividades y archivos de prácticas, el servicio
consulta al monolito mediante HTTP interno autenticado:
  GET  {URL}/practicas/{id_practica}/evidencias
  GET  {URL}/evidencias/{id_evidencia}
  GET  {URL}/evidencias/archivos/{id_archivo}
  GET  {URL}/actividades/{id_actividad}
  GET  {URL}/actividades/archivos/{id_archivo}
  GET  {URL}/verificar?tipo={tipo}&id={id}&id_practica={id_practica}

Modos (EVIDENCIAS_MODE):
  http  Modo producción / integración: consulta al monolito vía HTTP.
  stub  Modo pruebas offline: datos simulados para pytest y desarrollo sin red.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ..config import get_settings


class EvidenciasError(Exception):
    """El servicio de evidencias no respondió o el recurso no existe."""


@dataclass
class ArchivoInfo:
    id_archivo: str
    nombre: str
    mime: str | None = None


@dataclass
class EvidenciaInfo:
    id_evidencia: str
    descripcion: str | None = None
    horas_realizadas: float | None = None
    id_actividad: str | None = None
    nombre_actividad: str | None = None
    archivos: list[ArchivoInfo] = field(default_factory=list)
    id_practica: str | None = None


@dataclass
class ActividadInfo:
    id_actividad: str
    nombre: str
    descripcion: str | None = None
    archivos: list[ArchivoInfo] = field(default_factory=list)
    id_practica: str | None = None


@dataclass
class ArchivoBytes:
    data: bytes
    mime: str | None
    nombre: str


class EvidenciasClient(Protocol):
    def listar_evidencias(self, id_practica: str) -> list[EvidenciaInfo]: ...
    def obtener_evidencia(self, id_evidencia: str) -> EvidenciaInfo: ...
    def obtener_actividad(self, id_actividad: str) -> ActividadInfo: ...
    def descargar(self, tipo: str, id_archivo: str) -> ArchivoBytes: ...   # tipo: EVIDENCIA | ACTIVIDAD
    def pertenece(self, tipo_fuente: str, id_ref: str, id_practica: str) -> bool: ...
    """¿La evidencia/actividad/archivo `id_ref` es de la práctica `id_practica`? (evita leer datos ajenos)"""


# ----------------------------------------------------------------------------
#  Implementación HTTP: consulta al monolito (SOFTWARE_SPP)
# ----------------------------------------------------------------------------
def _archivos(raw: list[dict] | None) -> list[ArchivoInfo]:
    return [
        ArchivoInfo(str(a["id_archivo"]), a.get("nombre_archivo") or a.get("nombre") or f"archivo-{a['id_archivo']}",
                    a.get("tipo_mime"))
        for a in (raw or [])
    ]


def _evidencia(raw: dict) -> EvidenciaInfo:
    return EvidenciaInfo(
        id_evidencia=str(raw["id_evidencia"]),
        descripcion=raw.get("descripcion"),
        horas_realizadas=raw.get("horas_realizadas"),
        id_actividad=str(raw["id_actividad"]) if raw.get("id_actividad") is not None else None,
        nombre_actividad=raw.get("nombre_actividad"),
        archivos=_archivos(raw.get("archivos")),
        id_practica=str(raw["id_practica"]) if raw.get("id_practica") is not None else None,
    )


class HttpEvidenciasClient:
    """Cliente HTTP que consume los endpoints internos del monolito."""

    def __init__(self, base_url: str, token: str = "", max_bytes: int = 15 * 1024 * 1024):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30.0)
        self._max_bytes = max_bytes

    def _get(self, path: str) -> httpx.Response:
        try:
            r = self._http.get(path)
        except httpx.HTTPError as e:
            raise EvidenciasError(f"No se pudo contactar el servicio de evidencias: {e.__class__.__name__}") from e
        if r.status_code == 404:
            raise EvidenciasError(f"No existe en el servicio de evidencias: {path}")
        if r.status_code >= 400:
            raise EvidenciasError(f"El servicio de evidencias respondió {r.status_code} en {path}")
        return r

    def listar_evidencias(self, id_practica: str) -> list[EvidenciaInfo]:
        return [_evidencia(x) for x in self._get(f"/practicas/{id_practica}/evidencias").json()]

    def obtener_evidencia(self, id_evidencia: str) -> EvidenciaInfo:
        return _evidencia(self._get(f"/evidencias/{id_evidencia}").json())

    def obtener_actividad(self, id_actividad: str) -> ActividadInfo:
        raw = self._get(f"/actividades/{id_actividad}").json()
        return ActividadInfo(str(raw["id_actividad"]), raw.get("nombre", ""), raw.get("descripcion"),
                             _archivos(raw.get("archivos")),
                             str(raw["id_practica"]) if raw.get("id_practica") is not None else None)

    def pertenece(self, tipo_fuente: str, id_ref: str, id_practica: str) -> bool:
        """Verifica pertenencia consultando al monolito (/verificar?tipo=...&id=...&id_practica=...)."""
        try:
            r = self._get(f"/verificar?tipo={tipo_fuente}&id={id_ref}&id_practica={id_practica}")
            data = r.json()
            return bool(data.get("pertenece", False))
        except EvidenciasError:
            return False

    def descargar(self, tipo: str, id_archivo: str) -> ArchivoBytes:
        base = "/evidencias/archivos" if tipo == "EVIDENCIA" else "/actividades/archivos"
        r = self._get(f"{base}/{id_archivo}")
        if len(r.content) > self._max_bytes:
            raise EvidenciasError("El archivo supera el tamaño máximo permitido.")
        cd = r.headers.get("content-disposition", "")
        nombre = f"archivo-{id_archivo}"
        if "filename=" in cd:
            nombre = cd.split("filename=")[-1].strip().strip('"; ')
        return ArchivoBytes(r.content, r.headers.get("content-type"), nombre)


# ----------------------------------------------------------------------------
#  Implementación Stub (test double para tests unitarios automatizados)
# ----------------------------------------------------------------------------
_STUB_TEXTOS = {
    "1001": ("planeacion_clase.txt", (
        "Planeación de la clase de fracciones. El objetivo de aprendizaje es que los estudiantes "
        "comparen fracciones con distinto denominador usando representaciones gráficas. "
        "La clase inicia con una actividad de exploración donde cada grupo reparte una pizza de cartulina. "
        "Durante el desarrollo, el docente usa material concreto para mostrar fracciones equivalentes. "
        "Al cierre, los estudiantes completan una evaluación formativa breve de tres preguntas. "
        "Se observó que los estudiantes con ritmo más lento necesitaron un ejemplo adicional con regletas. "
        "La retroalimentación inmediata permitió corregir el error de sumar numeradores y denominadores."
    )),
    "1002": ("diario_campo.txt", (
        "Diario de campo, semana tres. La institución cuenta con veinticinco estudiantes en el grado quinto. "
        "Se implementó trabajo cooperativo con roles rotativos: relator, cronometrista y verificador. "
        "El clima de aula mejoró cuando se establecieron acuerdos de convivencia construidos con los niños. "
        "La docente titular recomendó usar preguntas abiertas para fomentar el pensamiento crítico. "
        "Como reflexión, el practicante reconoce que debe diversificar las estrategias de evaluación."
    )),
}


class StubEvidenciasClient:
    """Implementación stub exclusivamente para pruebas unitarias offline (pytest)."""

    def listar_evidencias(self, id_practica: str) -> list[EvidenciaInfo]:
        return [
            EvidenciaInfo("101", "Planeación y ejecución de la clase de fracciones", 4.0, "5", "Clase de matemáticas",
                          [ArchivoInfo("1001", "planeacion_clase.txt", "text/plain")]),
            EvidenciaInfo("102", "Diario de campo de la semana 3", 6.0, "6", "Observación de aula",
                          [ArchivoInfo("1002", "diario_campo.txt", "text/plain")]),
        ]

    def obtener_evidencia(self, id_evidencia: str) -> EvidenciaInfo:
        for e in self.listar_evidencias("0"):
            if e.id_evidencia == str(id_evidencia):
                return e
        raise EvidenciasError(f"No existe la evidencia {id_evidencia} (modo stub).")

    def obtener_actividad(self, id_actividad: str) -> ActividadInfo:
        return ActividadInfo(str(id_actividad), "Clase de matemáticas",
                             "Diseñar y ejecutar una clase de fracciones para grado quinto.", [])

    def pertenece(self, tipo_fuente: str, id_ref: str, id_practica: str) -> bool:
        return True

    def descargar(self, tipo: str, id_archivo: str) -> ArchivoBytes:
        if str(id_archivo) not in _STUB_TEXTOS:
            raise EvidenciasError(f"No existe el archivo {id_archivo} (modo stub).")
        nombre, texto = _STUB_TEXTOS[str(id_archivo)]
        return ArchivoBytes(texto.encode("utf-8"), "text/plain", nombre)


def get_evidencias_client() -> EvidenciasClient:
    s = get_settings()
    if s.evidencias_mode == "http":
        if not s.evidencias_api_url:
            raise EvidenciasError("EVIDENCIAS_MODE=http pero falta configurar EVIDENCIAS_API_URL.")
        return HttpEvidenciasClient(s.evidencias_api_url, s.evidencias_api_token, s.max_file_mb * 1024 * 1024)
    if s.evidencias_mode == "stub":
        return StubEvidenciasClient()

    raise EvidenciasError(
        f"Modo de evidencias '{s.evidencias_mode}' no soportado. "
        "El microservicio de evaluación no puede conectarse directamente a la base de datos de prácticas; "
        "configure EVIDENCIAS_MODE=http para consultar el monolito."
    )
