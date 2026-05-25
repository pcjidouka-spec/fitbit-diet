import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

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


# --- Task 5.7: abort on manual log.json changes --------------------------


def test_publish_aborts_on_manual_log_changes(tmp_path):
    """If log.json has unstaged manual edits, publish must prompt
    via click.confirm. When the user answers no, publish must SystemExit
    rather than silently overwrite the manual edits."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    # First publish — clean run, no prompt expected.
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=50,
        weight_kg=70.0,
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    # Manually corrupt the just-committed log.json (no `git add`).
    log_file = repo / "content/diet/log.json"
    log_file.write_text(log_file.read_text(encoding="utf-8") + "\n# manual mess",
                        encoding="utf-8")
    # Second publish — must detect the unstaged diff, prompt, and abort on no.
    rec2 = PublicDayRecord(
        date=date(2026, 5, 26),
        steps=2,
        distance_km=2.0,
        exercise_kcal=60,
        weight_kg=70.0,
    )
    with patch("click.confirm", return_value=False):
        with pytest.raises(SystemExit):
            publish_to_hpasaneel(repo, "content/diet", [rec2], do_push=False)


def test_publish_overwrites_dirty_log_when_user_confirms(tmp_path):
    """When the user confirms 'yes' to overwrite manual log.json edits, the
    dirty working-tree content must be DISCARDED before merge — otherwise
    the next json.loads either crashes (invalid JSON) or silently keeps
    whatever bogus fields the user typed in.

    Regression test for codex review P2 finding on commit 3525e36."""
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
    # Inject invalid trailing garbage that would crash json.loads.
    log_file.write_text(log_file.read_text(encoding="utf-8") + "\n# manual mess",
                        encoding="utf-8")
    rec2 = PublicDayRecord(
        date=date(2026, 5, 26),
        steps=2,
        distance_km=2.0,
        exercise_kcal=60,
        weight_kg=70.0,
    )
    # User confirms overwrite — must NOT crash, must produce a clean log.json.
    with patch("click.confirm", return_value=True):
        publish_to_hpasaneel(repo, "content/diet", [rec2], do_push=False)
    import json as _json
    final = _json.loads(log_file.read_text(encoding="utf-8"))
    dates = [d["date"] for d in final["days"]]
    # The new date got published, the old committed date is preserved,
    # and the "# manual mess" garbage is gone.
    assert "2026-05-26" in dates
    assert "2026-05-25" in dates
    assert "manual mess" not in log_file.read_text(encoding="utf-8")


def test_publish_recovers_from_staged_but_new_log(tmp_path):
    """Staged but never-committed log.json (failed first publish residue) is
    overwritten cleanly when the user confirms.

    Regression test for codex review P2 finding: the original recovery path
    used `git checkout HEAD --` unconditionally, which fails when the file is
    in status `A` (staged-add, no HEAD version to restore from)."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    # Simulate a failed first publish: write log.json + stage it but don't commit
    log_path = repo / "content/diet/log.json"
    log_path.write_text('{"updated_at": "2026-01-01T00:00:00+09:00", "days": []}')
    subprocess.run(["git", "add", "content/diet/log.json"], cwd=repo, check=True)
    # Status should be `A  content/diet/log.json`
    status = subprocess.run(
        ["git", "status", "--porcelain", "content/diet/log.json"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert status.startswith("A "), f"setup expects status 'A ', got: {status!r}"
    # Now run publish with user confirming overwrite
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=70.0,
    )
    with patch("click.confirm", return_value=True):
        publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    # Should have committed exactly one file with the 2026-05-25 entry
    last_files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    assert last_files == ["content/diet/log.json"]
    import json
    final = json.loads(log_path.read_text())
    assert any(d["date"] == "2026-05-25" for d in final["days"])
