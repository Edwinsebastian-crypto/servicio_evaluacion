"""Reglas de calificación. Funciones sobre objetos ORM; no hacen commit."""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import Evaluacion, IntentoEvaluacion, Pregunta, Respuesta


def _redondear(x: float) -> float:
    return round(x + 1e-9, 2)


def tiene_texto(r: Respuesta | None) -> bool:
    return bool(r and r.respuesta and r.respuesta.strip())


def calificar_auto(pregunta: Pregunta, r: Respuesta) -> None:
    """Califica selección múltiple y verdadero/falso al instante; deja las abiertas pendientes
    (salvo que estén en blanco: 0 automático)."""
    if pregunta.tipo_pregunta in ("OPCION_MULTIPLE", "VERDADERO_FALSO"):
        elegida = next((o for o in pregunta.opciones if o.id_opcion == r.id_opcion), None)
        if elegida is None:
            r.id_opcion, r.respuesta, r.es_correcta, r.nota_obtenida = None, None, False, 0.0
        else:
            r.respuesta = elegida.texto
            r.es_correcta = bool(elegida.es_correcta)
            r.nota_obtenida = float(pregunta.valor_pregunta) if elegida.es_correcta else 0.0
        r.calificada_por = "AUTO"
    else:  # ABIERTA
        if r.calificada_por == "TUTOR":
            return
        if not tiene_texto(r):
            r.es_correcta, r.nota_obtenida, r.calificada_por = False, 0.0, "AUTO"
        else:
            r.es_correcta, r.nota_obtenida, r.calificada_por = None, None, None


def pregunta_pendiente(pregunta: Pregunta, r: Respuesta | None) -> bool:
    return pregunta.tipo_pregunta == "ABIERTA" and tiene_texto(r) and r.nota_obtenida is None


def recalcular_intento(ev: Evaluacion, intento: IntentoEvaluacion, aprobadas: list[Pregunta]) -> int:
    """Actualiza nota y estado del intento. Devuelve cuántas respuestas siguen pendientes."""
    por_pregunta = {r.id_pregunta: r for r in intento.respuestas}
    total_valor = sum(float(p.valor_pregunta) for p in aprobadas)
    obtenido = sum(float(por_pregunta[p.id_pregunta].nota_obtenida or 0)
                   for p in aprobadas if p.id_pregunta in por_pregunta)
    pendientes = sum(1 for p in aprobadas if pregunta_pendiente(p, por_pregunta.get(p.id_pregunta)))

    intento.nota_obtenida = _redondear(obtenido / total_valor * float(ev.nota_maxima)) if total_valor else 0.0
    if intento.estado != "EN_CURSO":
        intento.estado = "CALIFICADO" if pendientes == 0 else "ENVIADO"
    return pendientes


def actualizar_nota_final(ev: Evaluacion) -> None:
    """La nota final de la evaluación es la mejor entre sus intentos ya calificados."""
    notas = [i.nota_obtenida for i in ev.intentos if i.estado == "CALIFICADO" and i.nota_obtenida is not None]
    ev.nota_final = max(notas) if notas else None


def aprobadas_de(ev: Evaluacion) -> list[Pregunta]:
    return [p for p in ev.preguntas if p.estado_revision == "APROBADA"]


def finalizar_intento(ev: Evaluacion, intento: IntentoEvaluacion) -> int:
    """Cierra un intento: crea las respuestas en blanco que falten, califica lo automático,
    fija nota y estado y actualiza la nota final. Devuelve cuántas respuestas quedan pendientes."""
    aprobadas = aprobadas_de(ev)
    existentes = {r.id_pregunta: r for r in intento.respuestas}
    for p in aprobadas:
        r = existentes.get(p.id_pregunta)
        if r is None:
            r = Respuesta(id_pregunta=p.id_pregunta)
            intento.respuestas.append(r)
        calificar_auto(p, r)
    intento.estado = "ENVIADO"
    intento.fecha_envio = datetime.now(timezone.utc)
    pendientes = recalcular_intento(ev, intento, aprobadas)
    actualizar_nota_final(ev)
    return pendientes


def vencida(ev: Evaluacion) -> bool:
    if ev.fecha_limite is None:
        return False
    limite = ev.fecha_limite if ev.fecha_limite.tzinfo else ev.fecha_limite.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > limite
