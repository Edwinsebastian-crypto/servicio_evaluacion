"""Reglas de estructura de una pregunta (las usan el alta manual y la salida de la IA)."""
from __future__ import annotations

from typing import Iterable

TIPOS = ("OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA")
DIFICULTADES = ("FACIL", "MEDIA", "DIFICIL")

MIN_OPCIONES = 2
MAX_OPCIONES = 6


def validar_estructura(tipo: str, opciones: Iterable[tuple[str, bool]]) -> None:
    """Lanza ValueError con un mensaje legible si las opciones no cuadran con el tipo."""
    ops = [(t.strip(), bool(c)) for t, c in opciones]

    if tipo == "ABIERTA":
        if ops:
            raise ValueError("Una pregunta abierta no lleva opciones.")
        return

    if tipo not in ("OPCION_MULTIPLE", "VERDADERO_FALSO"):
        raise ValueError(f"Tipo de pregunta no válido: {tipo}")

    if any(not t for t, _ in ops):
        raise ValueError("Ninguna opción puede estar vacía.")

    correctas = sum(1 for _, c in ops if c)
    if correctas != 1:
        raise ValueError("Debe haber exactamente una opción correcta.")

    textos = [t.casefold() for t, _ in ops]
    if len(set(textos)) != len(textos):
        raise ValueError("Las opciones no pueden repetirse.")

    if tipo == "VERDADERO_FALSO":
        if len(ops) != 2:
            raise ValueError("Verdadero/Falso necesita exactamente 2 opciones.")
    else:
        if not (MIN_OPCIONES <= len(ops) <= MAX_OPCIONES):
            raise ValueError(f"Opción múltiple necesita entre {MIN_OPCIONES} y {MAX_OPCIONES} opciones.")
