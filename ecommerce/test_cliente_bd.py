from unittest.mock import Mock, patch

import requests

import cliente_bd as bd
import config


def _espera_error(fn, *args, tipo=ValueError):
    try:
        fn(*args)
    except tipo:
        return
    raise AssertionError(f"{fn.__name__}{args!r} debió lanzar {tipo.__name__}")


def probar_config():
    assert config.DIMENSION == 256
    assert config.DESCRIPTOR_VISUAL == "sift:gray:max512:nf500"
    assert config.METODO_VECTORIAL == "HNSW"
    assert config.FUSION_DEFECTO in config.FUSIONES
    assert set(config.PESOS_DEFECTO) == {"cocompra", "visual", "texto", "metadata"}
    assert abs(sum(config.PESOS_DEFECTO.values()) - 1.0) < 1e-9
    assert config.K_SUCURSALES_KNN >= 1
    assert config.ESCALA_ESPACIAL_M > 0
    assert config.PESO_ESPACIAL_DEFECTO > 0

    tablas_ecom = [config.TABLA_SUCURSALES, config.TABLA_CATALOGO, config.TABLA_ORDENES]
    assert len(set(tablas_ecom)) == 3

    existentes = ["productos", "clientes", "ventas", "tiendas", "pedidos", "articulos", "chunks"]
    todas = tablas_ecom + existentes
    for nombre in tablas_ecom:
        assert nombre not in existentes
    for a in todas:
        for b in todas:
            if a != b:
                assert not b.startswith(a + "_"), f"colisión de prefijo entre '{a}' y '{b}'"


def probar_formateadores():
    assert bd.texto_sql(None) == "NULL"
    assert bd.texto_sql("Mouse RGB") == "'Mouse RGB'"
    assert bd.texto_sql("Assassin's Creed") == "'Assassin''s Creed'"
    texto_limpio = bd.texto_sql("Linea 1\nLinea 2\r\nIt's\x00 ok")
    assert texto_limpio == "'Linea 1 Linea 2 It''s ok'"
    assert "\n" not in texto_limpio and "\r" not in texto_limpio and "\x00" not in texto_limpio

    assert bd.numero_sql(None) == "NULL"
    assert bd.numero_sql(42) == "42"
    assert bd.numero_sql(19.99) == "19.99"
    for malo in (True, False, float("nan"), float("inf"), float("-inf")):
        _espera_error(bd.numero_sql, malo)

    assert bd.punto_sql(None, -77.0428) == "NULL"
    assert bd.punto_sql(-12.0464, None) == "NULL"
    assert bd.punto_sql(-12.0464, -77.0428) == "POINT(-12.046400, -77.042800)"
    for lat, lon in ((True, 0), (0, False), (float("nan"), 0), (0, float("inf")), (95, -77), (-12, -190)):
        _espera_error(bd.punto_sql, lat, lon)

    assert bd.vector_sql([0.5, -0.1234567, 1]) == "VECTOR(0.5, -0.123457, 1)"
    largo = bd.vector_sql(range(1, 10))
    assert bd._abreviar_vectores(f"WHERE SIMILAR_TO({largo}, k=3)") == "WHERE SIMILAR_TO(VECTOR(1, 2, 3, … 9 valores), k=3)"
    assert bd._abreviar_vectores("VECTOR(1, 2)") == "VECTOR(1, 2)"
    for vec in ([], [True], [0.1, float("nan")], [float("inf")]):
        _espera_error(bd.vector_sql, vec)

    assert bd.lista_sql([1, 2, 3]) == "(1, 2, 3)"
    assert bd.lista_sql(x for x in (10, 20)) == "(10, 20)"
    for vals in ([], [True], [1, False]):
        _espera_error(bd.lista_sql, vals)


def probar_cliente_http():
    respuesta_ok = Mock()
    respuesta_ok.json.return_value = {"rows": [{"id": 1, "nombre": "Demo"}]}
    with patch("cliente_bd.requests.post", return_value=respuesta_ok) as post_mock:
        assert bd.filas("SELECT * FROM catalogo;") == [{"id": 1, "nombre": "Demo"}]
        post_mock.assert_called_once_with(
            config.URL_MOTOR + "/api/query",
            json={"sql": "SELECT * FROM catalogo;"},
            timeout=1800,
        )

    respuesta_plan = Mock()
    respuesta_plan.json.return_value = {
        "rows": [], "plan": [{"op": "Seq Scan", "rows": 0}], "elapsedMs": 1.5,
    }
    with patch("cliente_bd.requests.post", return_value=respuesta_plan):
        bd.filas("SELECT 0;")  # fuera del bloque: no se registra
        with bd.registrar_consultas() as consultas:
            bd.filas("SELECT 1;")
            bd.filas("SELECT 2;")
        bd.filas("SELECT 3;")
    assert [c["sql"] for c in consultas] == ["SELECT 1;", "SELECT 2;"]
    assert consultas[0]["plan"] == [{"op": "Seq Scan", "rows": 0}]
    assert consultas[0]["ms_motor"] == 1.5 and consultas[0]["ms_total"] >= 0

    respuesta_error = Mock()
    respuesta_error.json.return_value = {"error": "tabla inexistente"}
    with patch("cliente_bd.requests.post", return_value=respuesta_error):
        _espera_error(bd.ejecutar, "SELECT * FROM nada;", tipo=bd.ErrorMotor)

    respuesta_http = Mock()
    respuesta_http.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    with patch("cliente_bd.requests.post", return_value=respuesta_http):
        _espera_error(bd.ejecutar, "SELECT 1;", tipo=requests.HTTPError)

    respuesta_feat = Mock()
    respuesta_feat.json.return_value = {"message": "características cargadas", "rowsLoaded": 10}
    with patch("cliente_bd.requests.post", return_value=respuesta_feat) as feat_mock:
        res = bd.cargar_caracteristicas("catalogo", "imagen", config.DESCRIPTOR_VISUAL)
        assert res["rowsLoaded"] == 10
        feat_mock.assert_called_once_with(
            config.URL_MOTOR + "/api/tables/catalogo/features",
            json={"path_column": "imagen", "descriptor_id": config.DESCRIPTOR_VISUAL},
            timeout=1800,
        )

    respuesta_feat_err = Mock()
    respuesta_feat_err.json.return_value = {"error": "sin descriptor"}
    with patch("cliente_bd.requests.post", return_value=respuesta_feat_err):
        _espera_error(bd.cargar_caracteristicas, "catalogo", "imagen", "malo", tipo=bd.ErrorMotor)

    respuesta_modelos = Mock()
    respuesta_modelos.json.return_value = {"models": [{"name": "fotos", "dimension": 256}]}
    with patch("cliente_bd.requests.get", return_value=respuesta_modelos) as mod_mock:
        assert bd.modelos_multimedia() == [{"name": "fotos", "dimension": 256}]
        mod_mock.assert_called_once_with(config.URL_MOTOR + "/api/multimedia/models", timeout=30)

    respuesta_tablas = Mock()
    respuesta_tablas.json.return_value = [{"name": "catalogo"}]
    with patch("cliente_bd.requests.get", return_value=respuesta_tablas) as get_mock:
        assert bd.tablas() == [{"name": "catalogo"}]
        get_mock.assert_called_once_with(config.URL_MOTOR + "/api/tables", timeout=60)

    salud_ok = Mock(status_code=200)
    with patch("cliente_bd.requests.get", return_value=salud_ok) as health_mock:
        assert bd.disponible() is True
        health_mock.assert_called_once_with(config.URL_MOTOR + "/api/health", timeout=5)

    salud_mal = Mock(status_code=503)
    with patch("cliente_bd.requests.get", return_value=salud_mal):
        assert bd.disponible() is False

    with patch("cliente_bd.requests.get", side_effect=requests.RequestException("sin conexión")):
        assert bd.disponible() is False


if __name__ == "__main__":
    probar_config()
    probar_formateadores()
    probar_cliente_http()
    print("OK: ecommerce config y cliente_bd")
