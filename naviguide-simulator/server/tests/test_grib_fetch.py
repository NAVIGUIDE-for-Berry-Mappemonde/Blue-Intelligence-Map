from datetime import datetime, timezone

import grib_fetch
import saildocs
from grib_fetch import fetch_latest_payload, is_stale
from saildocs import last_ready_cycle, to_iso


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params=None):
        times = [
            "2026-09-15T12:00",
            "2026-09-15T18:00",
            "2026-09-16T00:00",
        ]
        if "marine" in url:
            return _Resp({
                "hourly": {
                    "time": times,
                    "wave_height": [1.4, 1.6, 1.8],
                    "wave_direction": [210, 220, 230],
                    "wave_period": [8, 8.5, 9],
                }
            })
        return _Resp({
            "hourly": {
                "time": times,
                "wind_speed_10m": [12.0, 14.0, 11.0],
                "wind_direction_10m": [240, 250, 260],
                "pressure_msl": [1014.0, 1013.0, 1012.0],
                "rain": [0.0, 0.2, 0.0],
            }
        })


def test_fetch_latest_payload_uses_gfs_and_wave(monkeypatch):
    monkeypatch.setattr(grib_fetch.httpx, "Client", _Client)
    when = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    payload = fetch_latest_payload(
        {"lat": 14.6, "lon": -61.07, "dest": {"lat": 14.0, "lon": -62.0}},
        when,
    )
    assert payload["model"].startswith("GFS")
    assert payload["waveModel"].startswith("GFS-Wave")
    assert payload["source"] == "openmeteo"
    ids = {p["id"]: p["status"] for p in payload["products"]}
    assert ids["gfs"] == "ready"
    assert ids["gfswave"] == "ready"
    assert ids["rtofs"] == "absent"
    assert any(s.get("windKnots") == 12.0 for s in payload["samples"])
    assert any(s.get("pressHpa") == 1014.0 for s in payload["samples"])
    assert any(s.get("hs") == 1.4 for s in payload["samples"])
    assert payload["queries"][2]["query"].startswith("RTOFS:")


def test_stale_when_older_cycle():
    when = datetime(2026, 9, 15, 17, tzinfo=timezone.utc)
    old = {
        "status": "ready",
        "cycle": to_iso(datetime(2026, 9, 15, 6, tzinfo=timezone.utc)),
    }
    fresh = {
        "status": "ready",
        "cycle": to_iso(last_ready_cycle(when)),
    }
    assert is_stale(old, when) is True
    assert is_stale(fresh, when) is False
    assert is_stale(None, when) is True


def test_save_latest_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(saildocs, "GRIB_DIR", tmp_path)
    rec = saildocs.ingest_daily(
        "berry-mappemonde-2026-officiel",
        {
            "model": "GFS",
            "day": "2026-09-15",
            "issued": "2026-09-15T10:00:00Z",
            "cycle": "2026-09-15T06:00:00Z",
            "around": {"lat": 14.6, "lon": -61.07},
            "samples": [{"lat": 14.6, "lon": -61.07, "t": "2026-09-15T12:00:00Z", "windKnots": 8}],
        },
    )
    assert rec["status"] == "ready"
    newer = saildocs.ingest_daily(
        "berry-mappemonde-2026-officiel",
        {
            "model": "GFS 0.25° (Open-Meteo)",
            "day": "2026-09-15",
            "issued": "2026-09-15T16:00:00Z",
            "cycle": "2026-09-15T12:00:00Z",
            "around": {"lat": 14.7, "lon": -61.2},
            "samples": [{"lat": 14.7, "lon": -61.2, "t": "2026-09-15T16:00:00Z", "windKnots": 15}],
        },
    )
    loaded = saildocs.load_latest("berry-mappemonde-2026-officiel")
    assert loaded["issued"] == newer["issued"]
    assert loaded["samples"][0]["windKnots"] == 15
    stale = tmp_path / "berry-mappemonde-2026-officiel_2026-09-01.json"
    stale.write_text("{}", encoding="utf-8")
    saildocs.purge_old_grib_files("berry-mappemonde-2026-officiel")
    assert not stale.exists()
    assert saildocs.latest_path("berry-mappemonde-2026-officiel").exists()
