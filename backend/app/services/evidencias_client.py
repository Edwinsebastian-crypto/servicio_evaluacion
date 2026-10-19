"""Acceso a las evidencias y actividades de las prácticas (viven FUERA de esta base).

Tres modos (EVIDENCIAS_MODE):
  stub        datos de ejemplo, para desarrollo sin nada más.
  practice_db lee, en SOLO LECTURA, la base de PRÁCTICAS del monolito (evidenciaactividad,
              evidenciaarchivo, actividad, archivosactividad) y descarga los archivos desde su URL
              (Cloudinary). Es el modo para acoplar al monolito SPP.
  http        pide los datos a otro servicio por HTTP. Contrato (todas con
              `Authorization: Bearer <EVIDENCIAS_API_TOKEN>`; incluye `id_practica` en cada evidencia
              y actividad para que se pueda verificar que pertenecen a la práctica de la evaluación):

  GET  {URL}/practicas/{id_practica}/evidencias
       -> [ { "id_evidencia", "descripcion", "horas_realizadas", "id_actividad", "nombre_actividad",
              "archivos": [ {"id_archivo", "nombre_archivo", "tipo_mime"} ] } ]
  GET  {URL}/evidencias/{id_evidencia}                  -> un elemento como el anterior
  GET  {URL}/evidencias/archivos/{id_archivo}           -> bytes del archivo (Content-Type real)
  GET  {URL}/actividades/{id_actividad}
       -> { "id_actividad", "nombre", "descripcion",
            "archivos": [ {"id_archivo", "nombre_archivo", "tipo_mime"} ] }
  GET  {URL}/actividades/archivos/{id_archivo}          -> bytes del archivo
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
#  Implementación HTTP real
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
        """Solo se puede verificar con evidencias/actividades; para un archivo suelto no hay dato y se rechaza."""
        try:
            if tipo_fuente == "EVIDENCIA":
                dueña = self.obtener_evidencia(id_ref).id_practica
            elif tipo_fuente == "ACTIVIDAD":
                dueña = self.obtener_actividad(id_ref).id_practica
            else:
                return False
        except EvidenciasError:
            return False
        return dueña is not None and dueña == str(id_practica)

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
#  Lectura directa (solo lectura) de la base de PRÁCTICAS del monolito
# ----------------------------------------------------------------------------
# Nombres tal como los usa el monolito (ver src/repositories/evidence.repository.js).
SQL_EVIDENCIAS_DE_PRACTICA = """
    SELECT ev."idEvidencia" AS id_evidencia, ev.descripcion, ev."horasRealizadas" AS horas,
           ev."idActividad" AS id_actividad, a.nombre AS nombre_actividad, a."idPractica" AS id_practica,
           f."idArchivo" AS id_archivo, f."nombreArchivo" AS nombre_archivo, f."tipoMine" AS tipo_mime
      FROM evidenciaactividad ev
      JOIN actividad a ON a."idActividad" = ev."idActividad"
      LEFT JOIN evidenciaarchivo f ON f."idEvidenciaAct" = ev."idEvidencia"
     WHERE a."idPractica" = %s
     ORDER BY ev."idEvidencia" DESC, f."idArchivo" """
SQL_EVIDENCIA = SQL_EVIDENCIAS_DE_PRACTICA.replace('WHERE a."idPractica" = %s', 'WHERE ev."idEvidencia" = %s')
SQL_ACTIVIDAD = """
    SELECT a."idActividad" AS id_actividad, a.nombre, a.descripcion, a."idPractica" AS id_practica,
           f."idArchivoAct" AS id_archivo, f."nombreArchivo" AS nombre_archivo, f."tipoMine" AS tipo_mime
      FROM actividad a
      LEFT JOIN archivosactividad f ON f."idActividad" = a."idActividad"
     WHERE a."idActividad" = %s
     ORDER BY f."idArchivoAct" """
SQL_ARCHIVO_EVIDENCIA = """
    SELECT f."rutaArchivo" AS url, f."nombreArchivo" AS nombre, f."tipoMine" AS mime, a."idPractica" AS id_practica
      FROM evidenciaarchivo f
      JOIN evidenciaactividad ev ON ev."idEvidencia" = f."idEvidenciaAct"
      JOIN actividad a ON a."idActividad" = ev."idActividad"
     WHERE f."idArchivo" = %s"""
SQL_ARCHIVO_ACTIVIDAD = """
    SELECT f."rutaArchivo" AS url, f."nombreArchivo" AS nombre, f."tipoMine" AS mime, a."idPractica" AS id_practica
      FROM archivosactividad f
      JOIN actividad a ON a."idActividad" = f."idActividad"
     WHERE f."idArchivoAct" = %s"""
SQL_PRACTICA_DE_EVIDENCIA = """
    SELECT a."idPractica" AS id_practica FROM evidenciaactividad ev
      JOIN actividad a ON a."idActividad" = ev."idActividad" WHERE ev."idEvidencia" = %s"""
SQL_PRACTICA_DE_ACTIVIDAD = 'SELECT "idPractica" AS id_practica FROM actividad WHERE "idActividad" = %s'


def _conectar_practicas(url: str):
    """Conexión de SOLO LECTURA (la sesión rechaza cualquier INSERT/UPDATE/DELETE)."""
    import psycopg
    from psycopg.rows import dict_row

    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=10,
                           options="-c default_transaction_read_only=on -c statement_timeout=15000")


class PracticeDbEvidenciasClient:
    """Lee evidencias y actividades de la base de prácticas del monolito y baja los archivos de su URL.

    Seguridad: los archivos solo se descargan por HTTPS desde los dominios de `allowed_hosts`
    (Cloudinary por defecto), para que una URL manipulada en la base no sirva de puerta a la red interna.
    Recomendado: usa un usuario de Postgres con SOLO permiso SELECT en esas cuatro tablas.
    """

    def __init__(self, database_url: str, allowed_hosts: list[str], max_bytes: int = 15 * 1024 * 1024,
                 connect=None, http=None):
        self._url = database_url
        self._hosts = [h.lower() for h in allowed_hosts]
        self._max_bytes = max_bytes
        self._connect = connect or _conectar_practicas
        self._http = http or httpx.Client(timeout=30.0, follow_redirects=False)

    # -- base de datos ----------------------------------------------------
    def _rows(self, sql: str, param: str) -> list[dict]:
        try:
            with self._connect(self._url) as conn:
                return list(conn.execute(sql, (param,)).fetchall())
        except Exception as e:  # noqa: BLE001 — cualquier fallo de conexión/consulta se informa igual
            raise EvidenciasError(f"No se pudo leer la base de prácticas: {e.__class__.__name__}") from e

    @staticmethod
    def _agrupar(rows: list[dict]) -> list[EvidenciaInfo]:
        por_id: dict[str, EvidenciaInfo] = {}
        for r in rows:
            e = por_id.get(r["id_evidencia"])
            if e is None:
                e = por_id[r["id_evidencia"]] = EvidenciaInfo(
                    id_evidencia=r["id_evidencia"], descripcion=r["descripcion"],
                    horas_realizadas=float(r["horas"]) if r["horas"] is not None else None,
                    id_actividad=r["id_actividad"], nombre_actividad=r["nombre_actividad"],
                    id_practica=r["id_practica"])
            if r["id_archivo"]:
                e.archivos.append(ArchivoInfo(r["id_archivo"], r["nombre_archivo"] or f"archivo-{r['id_archivo']}",
                                              r["tipo_mime"]))
        return list(por_id.values())

    def listar_evidencias(self, id_practica: str) -> list[EvidenciaInfo]:
        return self._agrupar(self._rows(SQL_EVIDENCIAS_DE_PRACTICA, str(id_practica)))

    def obtener_evidencia(self, id_evidencia: str) -> EvidenciaInfo:
        lista = self._agrupar(self._rows(SQL_EVIDENCIA, str(id_evidencia)))
        if not lista:
            raise EvidenciasError(f"No existe la evidencia {id_evidencia}.")
        return lista[0]

    def obtener_actividad(self, id_actividad: str) -> ActividadInfo:
        rows = self._rows(SQL_ACTIVIDAD, str(id_actividad))
        if not rows:
            raise EvidenciasError(f"No existe la actividad {id_actividad}.")
        a = ActividadInfo(rows[0]["id_actividad"], rows[0]["nombre"], rows[0]["descripcion"],
                          id_practica=rows[0]["id_practica"])
        a.archivos = [ArchivoInfo(r["id_archivo"], r["nombre_archivo"] or f"archivo-{r['id_archivo']}", r["tipo_mime"])
                      for r in rows if r["id_archivo"]]
        return a

    def pertenece(self, tipo_fuente: str, id_ref: str, id_practica: str) -> bool:
        sql, param = {
            "EVIDENCIA": (SQL_PRACTICA_DE_EVIDENCIA, id_ref),
            "ACTIVIDAD": (SQL_PRACTICA_DE_ACTIVIDAD, id_ref),
            "ARCHIVO_EVIDENCIA": (SQL_ARCHIVO_EVIDENCIA, id_ref),
            "ARCHIVO_ACTIVIDAD": (SQL_ARCHIVO_ACTIVIDAD, id_ref),
        }.get(tipo_fuente, (None, None))
        if sql is None:
            return False
        try:
            rows = self._rows(sql, str(param))
        except EvidenciasError:
            return False
        return bool(rows) and rows[0]["id_practica"] == str(id_practica)

    # -- archivos ---------------------------------------------------------
    def _url_permitida(self, url: str) -> bool:
        from urllib.parse import urlparse

        u = urlparse(url or "")
        return u.scheme == "https" and (u.hostname or "").lower() in self._hosts

    def descargar(self, tipo: str, id_archivo: str) -> ArchivoBytes:
        rows = self._rows(SQL_ARCHIVO_EVIDENCIA if tipo == "EVIDENCIA" else SQL_ARCHIVO_ACTIVIDAD, str(id_archivo))
        if not rows:
            raise EvidenciasError(f"No existe el archivo {id_archivo}.")
        f = rows[0]
        if not self._url_permitida(f["url"]):
            raise EvidenciasError(f"El archivo «{f['nombre']}» está en un dominio no permitido y se omitió.")
        try:
            r = self._http.get(f["url"])
        except httpx.HTTPError as e:
            raise EvidenciasError(f"No se pudo descargar «{f['nombre']}»: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise EvidenciasError(f"No se pudo descargar «{f['nombre']}» (HTTP {r.status_code}).")
        if len(r.content) > self._max_bytes:
            raise EvidenciasError(f"«{f['nombre']}» supera el tamaño máximo permitido.")
        return ArchivoBytes(r.content, f["mime"] or r.headers.get("content-type"), f["nombre"])


# ----------------------------------------------------------------------------
#  Implementación de ejemplo (desarrollo, sin el otro servicio)
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
    """Datos de ejemplo para desarrollo. Útil junto con db/seed.sql (práctica 10)."""

    def listar_evidencias(self, id_practica: str) -> list[EvidenciaInfo]:
        return [
            EvidenciaInfo("101", "Planeación y ejecución de la clase de fracciones", 4.0, "5", "Clase de matemáticas",
                          [ArchivoInfo("1001", "planeacion_clase.txt", "text/plain")]),
            EvidenciaInfo("102", "Diario de campo de la semana 3", 6.0, "6", "Observación de aula",
                          [ArchivoInfo("1002", "diario_campo.txt", "text/plain")]),
        ]

    def obtener_evidencia(self, id_evidencia: str) -> EvidenciaInfo:
        for e in self.listar_evidencias(0):
            if e.id_evidencia == str(id_evidencia):
                return e
        raise EvidenciasError(f"No existe la evidencia {id_evidencia} (modo stub).")

    def obtener_actividad(self, id_actividad: str) -> ActividadInfo:
        return ActividadInfo(str(id_actividad), "Clase de matemáticas",
                             "Diseñar y ejecutar una clase de fracciones para grado quinto.", [])

    def pertenece(self, tipo_fuente: str, id_ref: str, id_practica: str) -> bool:
        return True   # datos de ejemplo: no hay prácticas reales que separar

    def descargar(self, tipo: str, id_archivo: str) -> ArchivoBytes:
        if str(id_archivo) not in _STUB_TEXTOS:
            raise EvidenciasError(f"No existe el archivo {id_archivo} (modo stub).")
        nombre, texto = _STUB_TEXTOS[str(id_archivo)]
        return ArchivoBytes(texto.encode("utf-8"), "text/plain", nombre)


def get_evidencias_client() -> EvidenciasClient:
    s = get_settings()
    if s.evidencias_mode == "practice_db":
        if not s.practice_database_url:
            raise EvidenciasError("EVIDENCIAS_MODE=practice_db pero falta PRACTICE_DATABASE_URL.")
        hosts = [h.strip() for h in s.allowed_file_hosts.split(",") if h.strip()]
        return PracticeDbEvidenciasClient(s.practice_database_url, hosts, s.max_file_mb * 1024 * 1024)
    if s.evidencias_mode == "http":
        if not s.evidencias_api_url:
            raise EvidenciasError("EVIDENCIAS_MODE=http pero falta EVIDENCIAS_API_URL.")
        return HttpEvidenciasClient(s.evidencias_api_url, s.evidencias_api_token, s.max_file_mb * 1024 * 1024)
    return StubEvidenciasClient()
