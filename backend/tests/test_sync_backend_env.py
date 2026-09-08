"""sync_backend_env — aucun réseau, aucun secret réel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sync_backend_env import mongo_kind, plan_sync, sync_file  # noqa: E402


class TestMongoKind:
    def test_atlas_srv(self):
        assert mongo_kind("mongodb+srv://u:p@cluster.mongodb.net") == "atlas"

    def test_localhost(self):
        assert mongo_kind("mongodb://localhost:27017") == "localhost"


class TestPlanSync:
    def test_atlas_process_replaces_file_localhost(self):
        out = plan_sync(
            {"MONGO_URL": "mongodb://localhost:27017", "DB_NAME": "app"},
            {"MONGO_URL": "mongodb+srv://u:p@cluster.mongodb.net/app",
             "NVIDIA_API_KEY": "nvapi-x"},
        )
        assert mongo_kind(out["MONGO_URL"]) == "atlas"
        assert out["DB_NAME"] == "app"
        assert out["NVIDIA_API_KEY"] == "nvapi-x"

    def test_does_not_overwrite_existing_key(self):
        out = plan_sync(
            {"MONGO_URL": "mongodb+srv://u:p@cluster.mongodb.net",
             "NVIDIA_API_KEY": "keep"},
            {"NVIDIA_API_KEY": "other"},
        )
        assert out["NVIDIA_API_KEY"] == "keep"

    def test_keeps_localhost_if_process_empty(self):
        out = plan_sync({"MONGO_URL": "mongodb://127.0.0.1:27017"}, {})
        assert mongo_kind(out["MONGO_URL"]) == "localhost"


class TestSyncFile:
    def test_writes_atlas_over_localhost(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("MONGO_URL=mongodb://localhost:27017\nCORS_ORIGINS=*\n")
        info = sync_file(p, {"MONGO_URL": "mongodb+srv://u:p@x.mongodb.net/db"})
        assert info["mongo_before"] == "localhost"
        assert info["mongo_after"] == "atlas"
        text = p.read_text()
        assert "mongodb.net" in text
        assert "CORS_ORIGINS=*" in text
