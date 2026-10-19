"""Flujo completo contra la API (SQLite en memoria de archivo + IA simulada)."""
from .conftest import ESTUDIANTE, OTRO_ESTUDIANTE, OTRO_TUTOR, TUTOR

P = "/api/v1"


def _evaluacion(client, **extra):
    body = {"id_practica": "10", "id_estudiante": "2", "titulo": "Evaluación de prueba", **extra}
    r = client.post(f"{P}/tutor/evaluaciones", json=body, headers=TUTOR)
    assert r.status_code == 201, r.text
    return r.json()["id_evaluacion"]


def _pregunta_manual(client, ev, tipo, enunciado, ops=(), valor=1):
    r = client.post(f"{P}/tutor/evaluaciones/{ev}/preguntas", headers=TUTOR, json={
        "tipo_pregunta": tipo, "enunciado": enunciado, "valor_pregunta": valor,
        "opciones": [{"texto": t, "es_correcta": c} for t, c in ops]})
    assert r.status_code == 201, r.text
    return r.json()


def test_health_y_auth(client):
    r = client.get(f"{P}/health")
    assert r.status_code == 200 and r.json()["ia"]["proveedor"] == "mock"
    assert client.get(f"{P}/tutor/evaluaciones").status_code == 401
    assert client.get(f"{P}/tutor/evaluaciones", headers=ESTUDIANTE).status_code == 403
    assert client.get(f"{P}/estudiante/evaluaciones", headers=TUTOR).status_code == 403


def test_validacion_de_preguntas(client):
    ev = _evaluacion(client)
    r = client.post(f"{P}/tutor/evaluaciones/{ev}/preguntas", headers=TUTOR, json={
        "tipo_pregunta": "OPCION_MULTIPLE", "enunciado": "¿Cuál?", "opciones": [
            {"texto": "a", "es_correcta": True}, {"texto": "b", "es_correcta": True}]})
    assert r.status_code == 422


def test_otro_tutor_no_puede_tocar(client):
    ev = _evaluacion(client)
    assert client.get(f"{P}/tutor/evaluaciones/{ev}", headers=OTRO_TUTOR).status_code == 403


def test_generar_con_ia_revisar_y_publicar(client):
    ev = _evaluacion(client)
    ev_ids = client.get(f"{P}/tutor/evidencias", params={"id_practica": "10"}, headers=TUTOR).json()
    assert ev_ids and ev_ids[0]["archivos"]

    r = client.post(f"{P}/tutor/evaluaciones/{ev}/generar", headers=TUTOR, json={
        "fuentes": [{"tipo": "EVIDENCIA", "id_referencia": "101"}], "cantidad": 4,
        "tipos": ["OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA"], "dificultad": "MEDIA"})
    assert r.status_code == 201, r.text
    gen = r.json()
    assert gen["cantidad_generada"] == 4 and gen["estado"] == "COMPLETADA"
    assert all(p["origen"] == "IA" and p["estado_revision"] == "BORRADOR" for p in gen["preguntas"])

    # sin aprobar nada no se puede publicar
    assert client.post(f"{P}/tutor/evaluaciones/{ev}/publicar", headers=TUTOR).status_code == 422
    assert client.post(f"{P}/tutor/evaluaciones/{ev}/preguntas/aprobar-todas", headers=TUTOR).json() == {"aprobadas": 4}
    assert client.post(f"{P}/tutor/evaluaciones/{ev}/publicar", headers=TUTOR).status_code == 200

    det = client.get(f"{P}/tutor/evaluaciones/{ev}", headers=TUTOR).json()
    assert det["generaciones"][0]["cantidad_generada"] == 4 and det["contextos"]


def test_generar_sin_contexto_util(client):
    ev = _evaluacion(client)
    r = client.post(f"{P}/tutor/evaluaciones/{ev}/generar", headers=TUTOR, json={
        "fuentes": [{"tipo": "EVIDENCIA", "id_referencia": "no-existe"}], "cantidad": 2})
    assert r.status_code == 422


def test_flujo_estudiante_y_calificacion(client):
    ev = _evaluacion(client, intentos_permitidos=1)
    p1 = _pregunta_manual(client, ev, "OPCION_MULTIPLE", "¿Cuál es correcta?", [("Sí", True), ("No", False)])
    p2 = _pregunta_manual(client, ev, "VERDADERO_FALSO", "El cielo es verde", [("Verdadero", False), ("Falso", True)])
    p3 = _pregunta_manual(client, ev, "ABIERTA", "Explica tu práctica", valor=2)

    # borrador: el estudiante no la ve
    assert client.get(f"{P}/estudiante/evaluaciones", headers=ESTUDIANTE).json() == [] or \
        all(e["id_evaluacion"] != ev for e in client.get(f"{P}/estudiante/evaluaciones", headers=ESTUDIANTE).json())
    assert client.post(f"{P}/tutor/evaluaciones/{ev}/publicar", headers=TUTOR).status_code == 200

    assert client.post(f"{P}/estudiante/evaluaciones/{ev}/intentos", headers=OTRO_ESTUDIANTE).status_code == 404
    it = client.post(f"{P}/estudiante/evaluaciones/{ev}/intentos", headers=ESTUDIANTE).json()
    assert it["estado"] == "EN_CURSO" and len(it["preguntas"]) == 3
    # el estudiante nunca recibe cuál es la correcta mientras presenta
    assert all(o["es_correcta"] is None for q in it["preguntas"] for o in q["opciones"])

    ok = next(o for o in p1["opciones"] if o["es_correcta"])
    mal = next(o for o in p2["opciones"] if not o["es_correcta"])
    base = f"{P}/estudiante/intentos/{it['id_intento']}"
    assert client.put(f"{base}/respuestas/{p1['id_pregunta']}", json={"id_opcion": ok["id_opcion"]}, headers=ESTUDIANTE).status_code == 200
    assert client.put(f"{base}/respuestas/{p2['id_pregunta']}", json={"id_opcion": mal["id_opcion"]}, headers=ESTUDIANTE).status_code == 200
    assert client.put(f"{base}/respuestas/{p3['id_pregunta']}", json={"respuesta": "Adapté con regletas"}, headers=ESTUDIANTE).status_code == 200

    fin = client.post(f"{base}/enviar", headers=ESTUDIANTE).json()
    assert fin["estado"] == "ENVIADO" and fin["nota_obtenida"] is None   # falta la abierta
    assert client.post(f"{base}/enviar", headers=ESTUDIANTE).status_code == 409
    assert client.post(f"{P}/estudiante/evaluaciones/{ev}/intentos", headers=ESTUDIANTE).status_code == 409   # sin intentos

    # tutor califica la abierta: (1 + 0 + 1.5) / 4 * 5 = 3.13
    det = client.get(f"{P}/tutor/intentos/{it['id_intento']}", headers=TUTOR).json()
    abierta = next(r for r in det["respuestas"] if r["tipo_pregunta"] == "ABIERTA")
    assert abierta["pendiente"]
    r = client.post(f"{P}/tutor/respuestas/{abierta['id_respuesta']}/calificar", headers=TUTOR,
                    json={"nota_obtenida": 1.5, "comentario": "Buen trabajo"})
    assert r.status_code == 200 and r.json()["estado"] == "CALIFICADO" and r.json()["nota_obtenida"] == 3.13
    assert client.post(f"{P}/tutor/respuestas/{abierta['id_respuesta']}/calificar", headers=TUTOR,
                       json={"nota_obtenida": 9}).status_code == 422

    res = client.get(f"{base}", headers=ESTUDIANTE).json()
    assert res["nota_obtenida"] == 3.13 and res["resultados_visibles"]
    assert any("Buen trabajo" in r["retroalimentacion"] for r in res["respuestas"])
    lista = client.get(f"{P}/estudiante/evaluaciones", headers=ESTUDIANTE).json()
    assert next(e for e in lista if e["id_evaluacion"] == ev)["nota_final"] == 3.13

    # ya con intentos, no se tocan las preguntas
    assert client.delete(f"{P}/tutor/preguntas/{p1['id_pregunta']}", headers=TUTOR).status_code == 409
    assert client.delete(f"{P}/tutor/evaluaciones/{ev}", headers=TUTOR).status_code == 409
