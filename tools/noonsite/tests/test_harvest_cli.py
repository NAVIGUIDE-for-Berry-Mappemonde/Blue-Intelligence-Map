import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harvest import main


def test_all_rejects_login():
    assert main(["--all", "--login"]) == 2


def test_login_cap():
    assert main(["saba", "niue", "martinique", "guadeloupe", "--login"]) == 2
