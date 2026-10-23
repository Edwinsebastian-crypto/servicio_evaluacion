"""Cálculos del panel del director: funciones puras, sin base de datos."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.schemas_director import DetalleDirector, ListaDirector, ResumenDirector
from app.services import estadisticas as est

AHORA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def dias(n):
    return AHORA - timedelta(days=n)


def pregunta(i, tipo="OPCION_MULTIPLE", origen="MANUAL", estado="APROBADA", dif=None, valor=1.0):
    return NS(id_pregunta=i, orden=i, tipo_pregunta=tipo, enunciado=f"Pregunta {i}", valor_pregunta=valor,
              origen=origen, estado_revision=estado, dificultad=dif)


def resp(id_pregunta, correcta):
    return NS(id_pregunta=id_pregunta, es_correcta=correcta)


def intento(i, estado, nota=None, envio=None, respuestas=()):
    return NS(id_intento=i, numero_intento=i, estado=estado, fecha_inicio=dias(10), fecha_envio=envio,
              nota_obtenida=nota, respuestas=list(respuestas))


def evaluacion(i, estado="PUBLICADA", tutor="T1", practica="P1", est_="E1", creada=10, limite=None,
               preguntas=(), intentos=(), generaciones=(), nota_max=5.0):
    return NS(id_evaluacion=i, id_practica=practica, id_tutor=tutor, id_estudiante=est_, titulo=f"Eval {i}",
              descripcion=None, estado=estado, fecha_evaluacion=dias(creada), fecha_limite=limite,
              intentos_permitidos=1, nota_maxima=nota_max, mostrar_resultados=True,
              preguntas=list(preguntas), intentos=list(intentos), generaciones=list(generaciones))


def gen(i, estado="COMPLETADA", prov="openai_compat"):
    return NS(id_generacion=i, proveedor=prov, modelo="m", estado=estado, cantidad_solicitada=5,
              cantidad_generada=5, duracion_ms=900, created_at=dias(5))


def escenario():
    a = evaluacion(1, "CERRADA", "T1", "P1", "E1", creada=40,
                   preguntas=[pregunta(1, origen="IA", dif="FACIL"), pregunta(2, "ABIERTA", "IA", "RECHAZADA", "DIFICIL")],
                   intentos=[intento(1, "CALIFICADO", 4.0, dias(30),
                                     [resp(1, True), resp(2, False)])],
                   generaciones=[gen(1), gen(2, "FALLIDA")])
    b = evaluacion(2, "PUBLICADA", "T1", "P2", "E2", creada=9, limite=dias(2),
                   preguntas=[pregunta(3, "ABIERTA", dif="MEDIA")],
                   intentos=[intento(2, "ENVIADO", None, dias(5), [resp(3, None)])])
    c = evaluacion(3, "BORRADOR", "T2", "P3", "E3", creada=20, preguntas=[pregunta(4, origen="IA", estado="BORRADOR")])
    d = evaluacion(4, "PUBLICADA", "T2", "P4", "E4", creada=8, preguntas=[pregunta(5)])
    e = evaluacion(5, "CERRADA", "T2", "P5", "E5", creada=30, nota_max=10.0,
                   preguntas=[pregunta(6)], intentos=[intento(3, "CALIFICADO", 5.0, dias(20), [resp(6, False)])])
    return [a, b, c, d, e]


def test_porcentaje_y_nota_final():
    assert est.porcentaje(4.0, 5.0) == 80.0
    assert est.porcentaje(None, 5.0) is None and est.porcentaje(3, 0) is None
    ev = evaluacion(1, intentos=[intento(1, "CALIFICADO", 2.0), intento(2, "CALIFICADO", 3.5), intento(3, "ENVIADO", 5.0)])
    assert est.nota_final_calculada(ev) == 3.5      # el intento sin calificar no cuenta


def test_alertas_por_regla():
    ev = escenario()
    tipos = {e.id_evaluacion: [a["tipo"] for a in est.alertas_de(e, AHORA)] for e in ev}
    assert tipos[1] == []
    assert tipos[2] == ["REVISION_ATRASADA", "VENCIDA_SIN_CERRAR"]
    assert tipos[3] == ["BORRADOR_ANTIGUO"]
    assert tipos[4] == ["SIN_INTENTOS"]
    assert tipos[5] == []
    atrasada = est.alertas_de(ev[1], AHORA)[0]
    assert (atrasada["severidad"], atrasada["cantidad"], atrasada["dias"]) == ("ALTA", 1, 5)


def test_un_envio_reciente_no_es_alerta():
    ev = evaluacion(1, intentos=[intento(1, "ENVIADO", None, dias(1))])
    assert est.alertas_de(ev, AHORA) == []


def test_resumen_global_cifras():
    r = est.resumen_global(escenario(), AHORA)
    t = r["totales"]
    assert (t["evaluaciones"], t["practicas"], t["tutores"], t["estudiantes"]) == (5, 5, 2, 5)
    assert (t["preguntas"], t["intentos_iniciados"], t["intentos_pendientes_revision"],
            t["intentos_calificados"], t["evaluaciones_vencidas_sin_cerrar"]) == (6, 3, 1, 2, 1)
    assert r["por_estado"] == {"BORRADOR": 1, "PUBLICADA": 2, "CERRADA": 2}
    # notas finales: 4/5 = 80 % y 5/10 = 50 %  -> promedio 65, aprobó 1 de 2
    d = r["desempeno"]
    assert (d["evaluaciones_calificadas"], d["promedio_pct"], d["aprobacion_pct"], d["aprobadas"], d["reprobadas"]) == (2, 65.0, 50.0, 1, 1)
    assert [x["cantidad"] for x in d["distribucion"]] == [0, 0, 1, 0, 1]   # 50 % y 80 %
    assert sum(x["cantidad"] for x in d["distribucion"]) == d["evaluaciones_calificadas"]


def test_resumen_global_ia_y_preguntas():
    r = est.resumen_global(escenario(), AHORA)
    ia = r["ia"]
    assert (ia["preguntas"], ia["aprobadas"], ia["rechazadas"], ia["por_revisar"]) == (3, 1, 1, 1)
    assert ia["aceptacion_pct"] == 50.0 and ia["uso_pct"] == 50.0
    assert (ia["generaciones"], ia["generaciones_fallidas"]) == (2, 1)
    assert ia["por_proveedor"] == {"openai_compat": 2}
    assert r["preguntas"]["por_origen"] == {"IA": 3, "MANUAL": 3}
    assert r["preguntas"]["por_tipo"] == {"OPCION_MULTIPLE": 4, "VERDADERO_FALSO": 0, "ABIERTA": 2}
    assert r["preguntas"]["por_dificultad"]["SIN_DEFINIR"] == 3


def test_limite_exacto_del_ultimo_rango_cuenta():
    ev = [evaluacion(1, intentos=[intento(1, "CALIFICADO", 5.0, dias(1))])]
    dist = est.resumen_global(ev, AHORA)["desempeno"]["distribucion"]
    assert dist[-1]["cantidad"] == 1 and sum(x["cantidad"] for x in dist) == 1


def test_por_tutor_ordena_primero_a_quien_tiene_pendientes():
    r = est.resumen_global(escenario(), AHORA)
    t1 = next(t for t in r["por_tutor"] if t["id_tutor"] == "T1")
    assert r["por_tutor"][0]["id_tutor"] == "T1"
    assert (t1["evaluaciones"], t1["publicadas"], t1["pendientes_revision"], t1["intentos_calificados"],
            t1["espera_max_dias"], t1["promedio_pct"]) == (2, 1, 1, 1, 5, 80.0)


def test_historial_y_alertas_ordenadas():
    r = est.resumen_global(escenario(), AHORA)
    assert [m["mes"] for m in r["historial"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert sum(m["evaluaciones_creadas"] for m in r["historial"]) == 5
    assert r["alertas"][0]["severidad"] == "ALTA"
    assert [a["severidad"] for a in r["alertas"]] == sorted((a["severidad"] for a in r["alertas"]),
                                                            key=["ALTA", "MEDIA", "BAJA"].index)


def test_historial_cruza_el_cambio_de_anio():
    r = est.resumen_global([], datetime(2027, 2, 10, tzinfo=timezone.utc))
    assert [m["mes"] for m in r["historial"]][:2] == ["2026-09", "2026-10"] and r["historial"][-1]["mes"] == "2027-02"


def test_analisis_por_pregunta_no_expone_textos():
    ev = escenario()[0]
    filas = est.analisis_preguntas(ev)
    assert filas[0]["pct_acierto"] == 100.0 and filas[1]["pct_acierto"] == 0.0
    # solo cifras: ninguna fila trae lo que escribió el estudiante
    assert set(filas[0]) == {"id_pregunta", "orden", "tipo_pregunta", "enunciado", "valor_pregunta", "origen",
                             "estado_revision", "dificultad", "respuestas", "correctas", "incorrectas",
                             "sin_calificar", "pct_acierto"}
    assert isinstance(filas[0]["respuestas"], int)
    abierta = est.analisis_preguntas(escenario()[1])[0]
    assert abierta["sin_calificar"] == 1 and abierta["pct_acierto"] is None


def test_sin_datos_no_revienta():
    r = est.resumen_global([], AHORA)
    assert r["totales"]["evaluaciones"] == 0 and r["desempeno"]["promedio_pct"] is None
    assert r["desempeno"]["aprobacion_pct"] is None and r["ia"]["uso_pct"] is None and r["alertas"] == []


def test_respuestas_encajan_en_los_esquemas():
    evs = escenario()
    ResumenDirector.model_validate(est.resumen_global(evs, AHORA))
    filas = [est.resumen_evaluacion(e, AHORA) for e in evs]
    ListaDirector.model_validate({"total": 5, "limite": 25, "desplazamiento": 0, "items": filas})
    ev = evs[0]
    DetalleDirector.model_validate({
        **est.resumen_evaluacion(ev, AHORA), "descripcion": None, "mostrar_resultados": True,
        "preguntas": est.analisis_preguntas(ev), "intentos": est.intentos_de(ev, AHORA),
        "generaciones": est.generaciones_de(ev)})
