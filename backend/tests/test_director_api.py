"""Panel del director: solo lectura, solo para el rol DIRECTOR y sin exponer lo que escribió el estudiante."""
from .conftest import ESTUDIANTE, TUTOR
from .test_api import P, _evaluacion, _pregunta_manual

DIRECTOR = {"X-User-Id": "9", "X-User-Role": "DIRECTOR"}


def _evaluacion_presentada(client):
    ev = _evaluacion(client, titulo="Evaluación para el director")
    p1 = _pregunta_manual(client, ev, "OPCION_MULTIPLE", "¿Cuál es correcta?", [("Sí", True), ("No", False)])
    assert client.post(f"{P}/tutor/evaluaciones/{ev}/publicar", headers=TUTOR).status_code == 200
    it = client.post(f"{P}/estudiante/evaluaciones/{ev}/intentos", headers=ESTUDIANTE).json()
    ok = next(o for o in p1["opciones"] if o["es_correcta"])
    base = f"{P}/estudiante/intentos/{it['id_intento']}"
    assert client.put(f"{base}/respuestas/{p1['id_pregunta']}", json={"id_opcion": ok["id_opcion"]},
                      headers=ESTUDIANTE).status_code == 200
    assert client.post(f"{base}/enviar", headers=ESTUDIANTE).json()["estado"] == "CALIFICADO"
    return ev


def test_solo_el_director_entra(client):
    for ruta in ("/director/resumen", "/director/evaluaciones", "/director/evaluaciones/1"):
        assert client.get(f"{P}{ruta}").status_code == 401
        assert client.get(f"{P}{ruta}", headers=TUTOR).status_code == 403
        assert client.get(f"{P}{ruta}", headers=ESTUDIANTE).status_code == 403


def test_el_director_no_puede_escribir(client):
    assert client.post(f"{P}/director/evaluaciones", json={}, headers=DIRECTOR).status_code == 405
    assert client.delete(f"{P}/director/evaluaciones/1", headers=DIRECTOR).status_code == 405
    # ni usar las rutas del tutor o del estudiante
    assert client.post(f"{P}/tutor/evaluaciones", headers=DIRECTOR, json={
        "id_practica": "10", "id_estudiante": "2", "titulo": "No debería"}).status_code == 403
    assert client.get(f"{P}/estudiante/evaluaciones", headers=DIRECTOR).status_code == 403


def test_resumen_con_datos_reales(client):
    ev = _evaluacion_presentada(client)
    r = client.get(f"{P}/director/resumen", headers=DIRECTOR)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["totales"]["evaluaciones"] >= 1 and d["totales"]["intentos_calificados"] >= 1
    assert sum(d["por_estado"].values()) == d["totales"]["evaluaciones"]
    assert d["desempeno"]["promedio_pct"] is not None
    assert len(d["historial"]) == 6 and d["umbral_aprobacion_pct"] == 60
    assert any(t["id_tutor"] == "1" for t in d["por_tutor"])
    assert ev  # creada


def test_lista_filtra_y_pagina(client):
    ev = _evaluacion_presentada(client)
    todas = client.get(f"{P}/director/evaluaciones", headers=DIRECTOR).json()
    assert todas["total"] >= 1 and len(todas["items"]) <= todas["limite"]
    una = client.get(f"{P}/director/evaluaciones", params={"q": "para el director", "estado": "PUBLICADA"},
                     headers=DIRECTOR).json()
    assert any(i["id_evaluacion"] == ev for i in una["items"])
    assert all(i["estado"] == "PUBLICADA" for i in una["items"])
    assert client.get(f"{P}/director/evaluaciones", params={"id_tutor": "no-existe"}, headers=DIRECTOR).json()["total"] == 0
    assert client.get(f"{P}/director/evaluaciones", params={"estado": "OTRO"}, headers=DIRECTOR).status_code == 422
    assert client.get(f"{P}/director/evaluaciones", params={"limite": 0}, headers=DIRECTOR).status_code == 422
    pag = client.get(f"{P}/director/evaluaciones", params={"limite": 1}, headers=DIRECTOR).json()
    assert len(pag["items"]) == 1


def test_detalle_no_expone_respuestas_ni_prompt(client):
    ev = _evaluacion_presentada(client)
    r = client.get(f"{P}/director/evaluaciones/{ev}", headers=DIRECTOR)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["porcentaje_final"] == 100.0 and d["intentos_calificados"] == 1
    q = d["preguntas"][0]
    assert (q["respuestas"], q["correctas"], q["pct_acierto"]) == (1, 1, 100.0)
    assert d["intentos"][0]["estado"] == "CALIFICADO"
    assert "respuesta" not in q and "opciones" not in q          # solo cifras
    assert all("prompt_usado" not in g for g in d["generaciones"])
    assert client.get(f"{P}/director/evaluaciones/999999", headers=DIRECTOR).status_code == 404
