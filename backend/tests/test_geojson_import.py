from app.services.geojson_import import empty_import_result, parse_feature_collection


def test_parse_empty_feature_collection():
    kind, feats = parse_feature_collection({"type": "FeatureCollection", "features": []})
    assert kind == "empty"
    assert feats == []


def test_parse_invalid():
    kind, feats = parse_feature_collection({"type": "Feature"})
    assert kind == "invalid"
    assert empty_import_result("total_capitaineries", 3)["message"] == "rien à importer"


def test_parse_ok():
    kind, feats = parse_feature_collection({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": None}],
    })
    assert kind == "ok"
    assert len(feats) == 1
