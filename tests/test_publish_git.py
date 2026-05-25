import subprocess
from datetime import date
from pathlib import Path

from diet.publish import PublicDayRecord, publish_to_hpasaneel


def _init_repo(p: Path) -> None:
    """Initialise a real git repo with one initial commit so we have HEAD."""
    subprocess.run(["git", "init"], cwd=p, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=p, check=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=p, check=True)
    (p / "README.md").write_text("# t")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=p, check=True, capture_output=True
    )


def test_publish_creates_log_and_commits(tmp_path):
    """publish_to_hpasaneel writes log.json and produces a 'diet:' commit."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=50,
        weight_kg=70.0,
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    log_file = repo / "content/diet/log.json"
    assert log_file.exists()
    assert "2026-05-25" in log_file.read_text(encoding="utf-8")
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "diet:" in log.stdout


def test_publish_stages_only_log_json(tmp_path):
    """Other untracked files must remain untracked — `git add .` is forbidden."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    (repo / "untracked.txt").write_text("should not be committed")
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=50,
        weight_kg=70.0,
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "?? untracked.txt" in status.stdout
