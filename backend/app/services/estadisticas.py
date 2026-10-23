"""Estadísticas de SOLO LECTURA para el director.

Son funciones puras sobre objetos ORM (o cualquier objeto con los mismos atributos): no consultan la
base de datos, no hacen commit y no leen el texto de las respuestas de los estudiantes. Así se pueden
probar sin base de datos y el router queda delgado.

Definiciones (las mismas que explica la pantalla del director):
  · nota final de una evaluación = mejor nota entre sus intentos ya CALIFICADOS.
  · porcentaje = nota / nota_maxima de la evaluación (para poder comparar escalas distintas).
  · aprobada = porcentaje >= UMBRAL_APROBACION (60 % = 3.0 sobre 5.0).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

UMBRAL_APROBACION = 0.60          # 3.0 / 5.0
DIAS_REVISION_ATRASADA = 3        # un intento enviado espera calificación más de N días
DIAS_BORRADOR_ANTIGUO = 14        # un borrador sin publicar desde hace N días
DIAS_SIN_INTENTOS = 7             # publicada hace N días y nadie la ha presentado
MESES_HISTORIAL = 6
RANGOS_NOTA = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))   # % de la nota máxima

TIPOS = ("OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA")
DIFICULTADES = ("FACIL", "MEDIA", "DIFICIL")
ESTADOS_EVAL = ("BORRADOR", "PUBLICADA", "CERRADA")


# ---------------------------------------------------------------- utilidades
def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dias(desde: datetime | None, ahora: datetime) -> int | None:
    d = _aware(desde)
    return None if d is None else max(0, (ahora - d).days)


def porcentaje(nota: float | None, maxima: float | None) -> float | None:
    if nota is None or not maxima:
        return None
    return round(float(nota) / float(maxima) * 100, 1)


def _media(valores: list[float]) -> float | None:
    return round(sum(valores) / len(valores), 1) if valores else None


def _tasa(parte: int, total: int) -> float | None:
    return round(parte / total * 100, 1) if total else None


def _conteo(valores, claves) -> dict[str, int]:
    c = Counter(valores)
    return {k: c.get(k, 0) for k in claves}


# ---------------------------------------------------------------- por evaluación
def nota_final_calculada(ev) -> float | None:
    notas = [i.nota_obtenida for i in ev.intentos if i.estado == "CALIFICADO" and i.nota_obtenida is not None]
    return max(notas) if notas else None


def vencida(ev, ahora: datetime) -> bool:
    limite = _aware(ev.fecha_limite)
    return limite is not None and ahora > limite


def alertas_de(ev, ahora: datetime) -> list[dict]:
    """Situaciones que merecen atención. Cada alerta: tipo, severidad (ALTA|MEDIA|BAJA), cantidad, dias."""
    out: list[dict] = []
    esperando = [i for i in ev.intentos if i.estado == "ENVIADO"]
    atrasados = [i for i in esperando
                 if (_dias(i.fecha_envio, ahora) or 0) >= DIAS_REVISION_ATRASADA]
    if atrasados:
        out.append({"tipo": "REVISION_ATRASADA", "severidad": "ALTA", "cantidad": len(atrasados),
                    "dias": max(_dias(i.fecha_envio, ahora) or 0 for i in atrasados)})
    if ev.estado == "PUBLICADA" and vencida(ev, ahora):
        out.append({"tipo": "VENCIDA_SIN_CERRAR", "severidad": "MEDIA", "cantidad": None,
                    "dias": _dias(ev.fecha_limite, ahora)})
    edad = _dias(ev.fecha_evaluacion, ahora) or 0
    if ev.estado == "BORRADOR" and edad >= DIAS_BORRADOR_ANTIGUO:
        out.append({"tipo": "BORRADOR_ANTIGUO", "severidad": "BAJA", "cantidad": None, "dias": edad})
    if ev.estado == "PUBLICADA" and not ev.intentos and edad >= DIAS_SIN_INTENTOS:
        out.append({"tipo": "SIN_INTENTOS", "severidad": "BAJA", "cantidad": None, "dias": edad})
    return out


def resumen_evaluacion(ev, ahora: datetime) -> dict:
    """Una fila de la lista del director."""
    enviados = [i for i in ev.intentos if i.estado != "EN_CURSO"]
    pendientes = [i for i in ev.intentos if i.estado == "ENVIADO"]
    final = nota_final_calculada(ev)
    return {
        "id_evaluacion": ev.id_evaluacion, "id_practica": ev.id_practica, "id_tutor": ev.id_tutor,
        "id_estudiante": ev.id_estudiante, "titulo": ev.titulo, "estado": ev.estado,
        "fecha_evaluacion": ev.fecha_evaluacion, "fecha_limite": ev.fecha_limite,
        "vencida": vencida(ev, ahora), "intentos_permitidos": ev.intentos_permitidos,
        "nota_maxima": float(ev.nota_maxima),
        "total_preguntas": len(ev.preguntas),
        "preguntas_aprobadas": sum(1 for p in ev.preguntas if p.estado_revision == "APROBADA"),
        "preguntas_ia": sum(1 for p in ev.preguntas if p.origen == "IA"),
        "intentos_iniciados": len(ev.intentos), "intentos_enviados": len(enviados),
        "intentos_calificados": sum(1 for i in ev.intentos if i.estado == "CALIFICADO"),
        "pendientes_revision": len(pendientes),
        "espera_max_dias": max((_dias(i.fecha_envio, ahora) or 0 for i in pendientes), default=None),
        "nota_final": final, "porcentaje_final": porcentaje(final, ev.nota_maxima),
        "alertas": alertas_de(ev, ahora),
    }


# ---------------------------------------------------------------- detalle (análisis por pregunta)
def analisis_preguntas(ev) -> list[dict]:
    """Por pregunta: cuántos la acertaron. NO incluye lo que escribió cada estudiante."""
    enviados = [i for i in ev.intentos if i.estado != "EN_CURSO"]
    por_pregunta: dict[int, list] = {}
    for i in enviados:
        for r in i.respuestas:
            por_pregunta.setdefault(r.id_pregunta, []).append(r)
    filas = []
    for p in ev.preguntas:
        rs = por_pregunta.get(p.id_pregunta, [])
        ok = sum(1 for r in rs if r.es_correcta is True)
        mal = sum(1 for r in rs if r.es_correcta is False)
        sin = sum(1 for r in rs if r.es_correcta is None)
        filas.append({
            "id_pregunta": p.id_pregunta, "orden": p.orden, "tipo_pregunta": p.tipo_pregunta,
            "enunciado": p.enunciado, "valor_pregunta": float(p.valor_pregunta), "origen": p.origen,
            "estado_revision": p.estado_revision, "dificultad": p.dificultad,
            "respuestas": len(rs), "correctas": ok, "incorrectas": mal, "sin_calificar": sin,
            "pct_acierto": _tasa(ok, ok + mal),
        })
    return filas


def intentos_de(ev, ahora: datetime) -> list[dict]:
    return [{
        "id_intento": i.id_intento, "numero_intento": i.numero_intento, "estado": i.estado,
        "fecha_inicio": i.fecha_inicio, "fecha_envio": i.fecha_envio,
        "nota_obtenida": i.nota_obtenida, "porcentaje": porcentaje(i.nota_obtenida, ev.nota_maxima),
        "dias_esperando": _dias(i.fecha_envio, ahora) if i.estado == "ENVIADO" else None,
    } for i in ev.intentos]


def generaciones_de(ev) -> list[dict]:
    """Sin el prompt ni el texto de las evidencias: solo cómo se usó la IA."""
    return [{
        "id_generacion": g.id_generacion, "proveedor": g.proveedor, "modelo": g.modelo, "estado": g.estado,
        "cantidad_solicitada": g.cantidad_solicitada, "cantidad_generada": g.cantidad_generada,
        "duracion_ms": g.duracion_ms, "created_at": g.created_at,
    } for g in ev.generaciones]


# ---------------------------------------------------------------- global
def _meses(ahora: datetime) -> list[str]:
    y, m = ahora.year, ahora.month
    claves = []
    for _ in range(MESES_HISTORIAL):
        claves.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(claves))


def _clave_mes(dt: datetime | None) -> str | None:
    d = _aware(dt)
    return None if d is None else f"{d.year:04d}-{d.month:02d}"


def resumen_global(evaluaciones: list, ahora: datetime) -> dict:
    preguntas = [p for ev in evaluaciones for p in ev.preguntas]
    intentos = [i for ev in evaluaciones for i in ev.intentos]
    generaciones = [g for ev in evaluaciones for g in ev.generaciones]
    ia = [p for p in preguntas if p.origen == "IA"]
    ia_ok = sum(1 for p in ia if p.estado_revision == "APROBADA")
    ia_no = sum(1 for p in ia if p.estado_revision == "RECHAZADA")
    ia_pend = sum(1 for p in ia if p.estado_revision == "BORRADOR")

    # notas finales por evaluación (mejor intento calificado), en % de la nota máxima
    finales = [porcentaje(nota_final_calculada(ev), ev.nota_maxima) for ev in evaluaciones]
    finales = [f for f in finales if f is not None]
    rangos = []
    for n, (a, b) in enumerate(RANGOS_NOTA):
        ultimo = n == len(RANGOS_NOTA) - 1
        rangos.append({"desde": a, "hasta": b,
                       "cantidad": sum(1 for f in finales if a <= f < b or (ultimo and f == b))})
    aprobadas = sum(1 for f in finales if f >= UMBRAL_APROBACION * 100)

    # actividad por mes
    meses = _meses(ahora)
    creadas = Counter(_clave_mes(ev.fecha_evaluacion) for ev in evaluaciones)
    enviados = Counter(_clave_mes(i.fecha_envio) for i in intentos if i.fecha_envio)
    historial = [{"mes": m, "evaluaciones_creadas": creadas.get(m, 0), "intentos_enviados": enviados.get(m, 0)}
                 for m in meses]

    # por tutor
    por_tutor = []
    for tutor in sorted({ev.id_tutor for ev in evaluaciones}):
        evs = [ev for ev in evaluaciones if ev.id_tutor == tutor]
        its = [i for ev in evs for i in ev.intentos]
        pct_cal = [porcentaje(i.nota_obtenida, ev.nota_maxima)
                   for ev in evs for i in ev.intentos if i.estado == "CALIFICADO" and i.nota_obtenida is not None]
        esperas = [_dias(i.fecha_envio, ahora) or 0 for i in its if i.estado == "ENVIADO"]
        por_tutor.append({
            "id_tutor": tutor, "evaluaciones": len(evs),
            "publicadas": sum(1 for ev in evs if ev.estado == "PUBLICADA"),
            "intentos_calificados": sum(1 for i in its if i.estado == "CALIFICADO"),
            "pendientes_revision": len(esperas),
            "espera_max_dias": max(esperas, default=None),
            "promedio_pct": _media([x for x in pct_cal if x is not None]),
            "alertas": sum(len(alertas_de(ev, ahora)) for ev in evs),
        })
    por_tutor.sort(key=lambda t: (-t["pendientes_revision"], -t["evaluaciones"], t["id_tutor"]))

    # alertas (las más graves primero)
    orden = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
    alertas = []
    for ev in evaluaciones:
        for a in alertas_de(ev, ahora):
            alertas.append({**a, "id_evaluacion": ev.id_evaluacion, "titulo": ev.titulo,
                            "id_practica": ev.id_practica, "id_tutor": ev.id_tutor})
    alertas.sort(key=lambda a: (orden[a["severidad"]], -(a["dias"] or 0), a["id_evaluacion"]))

    return {
        "generado_en": ahora,
        "umbral_aprobacion_pct": UMBRAL_APROBACION * 100,
        "dias_revision_atrasada": DIAS_REVISION_ATRASADA,
        "dias_borrador_antiguo": DIAS_BORRADOR_ANTIGUO,
        "dias_sin_intentos": DIAS_SIN_INTENTOS,
        "totales": {
            "evaluaciones": len(evaluaciones),
            "practicas": len({ev.id_practica for ev in evaluaciones}),
            "tutores": len({ev.id_tutor for ev in evaluaciones}),
            "estudiantes": len({ev.id_estudiante for ev in evaluaciones}),
            "preguntas": len(preguntas),
            "intentos_iniciados": len(intentos),
            "intentos_en_curso": sum(1 for i in intentos if i.estado == "EN_CURSO"),
            "intentos_pendientes_revision": sum(1 for i in intentos if i.estado == "ENVIADO"),
            "intentos_calificados": sum(1 for i in intentos if i.estado == "CALIFICADO"),
            "evaluaciones_vencidas_sin_cerrar": sum(
                1 for ev in evaluaciones if ev.estado == "PUBLICADA" and vencida(ev, ahora)),
        },
        "por_estado": _conteo((ev.estado for ev in evaluaciones), ESTADOS_EVAL),
        "desempeno": {
            "evaluaciones_calificadas": len(finales),
            "promedio_pct": _media(finales),
            "aprobacion_pct": _tasa(aprobadas, len(finales)),
            "aprobadas": aprobadas, "reprobadas": len(finales) - aprobadas,
            "distribucion": rangos,
        },
        "preguntas": {
            "por_tipo": _conteo((p.tipo_pregunta for p in preguntas), TIPOS),
            "por_dificultad": {**_conteo((p.dificultad for p in preguntas if p.dificultad), DIFICULTADES),
                               "SIN_DEFINIR": sum(1 for p in preguntas if not p.dificultad)},
            "por_origen": {"IA": len(ia), "MANUAL": len(preguntas) - len(ia)},
        },
        "ia": {
            "preguntas": len(ia), "aprobadas": ia_ok, "rechazadas": ia_no, "por_revisar": ia_pend,
            "aceptacion_pct": _tasa(ia_ok, ia_ok + ia_no),
            "uso_pct": _tasa(len(ia), len(preguntas)),
            "generaciones": len(generaciones),
            "generaciones_fallidas": sum(1 for g in generaciones if g.estado == "FALLIDA"),
            "por_proveedor": dict(Counter(g.proveedor or "desconocido" for g in generaciones)),
        },
        "historial": historial,
        "por_tutor": por_tutor,
        "alertas": alertas,
    }


def filtrar_lista(filas: list[dict], solo_alertas: bool = False) -> list[dict]:
    return [f for f in filas if f["alertas"]] if solo_alertas else filas
