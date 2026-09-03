"""Страж приватности: user/ закрыт по умолчанию, шаблоны — по исключению.

Раньше .gitignore перечислял личные файлы по именам, и правило молча
открывалось: всё новое в user/ отслеживалось, пока кто-нибудь не вспомнит
дописать строку. 2026-09-02 так остались незащищёнными два личных черновика —
заявка на грант и переписанный профиль LinkedIn — в репозитории, у которого
есть remote на GitHub и публикуемая половина core/.

Тест держит форму правила, а не список файлов: любой НОВЫЙ файл в user/
обязан игнорироваться без правки .gitignore.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ignored(relative_path: str) -> bool:
    """git сам отвечает, попадёт ли путь в коммит — без имитации правил."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPO, capture_output=True,
    )
    return result.returncode == 0


def test_a_brand_new_personal_file_is_ignored_without_touching_gitignore():
    assert _ignored("user/some-personal-draft-2099.md")
    assert _ignored("user/notes/deep/inside.md")


def test_the_templates_that_make_the_repo_usable_stay_tracked():
    tracked = subprocess.run(
        ["git", "ls-files", "user/"], cwd=REPO, capture_output=True, text=True,
    ).stdout.split()
    assert "user/profile.example.md" in tracked
    assert "user/glossary.example.md" in tracked
    assert "user/secrets.env.example" in tracked
    assert "user/projects/example.example.md" in tracked
    for path in tracked:
        assert not _ignored(path), f"шаблон {path} стал невидимым для git"


def test_real_secrets_and_profile_never_slip_through():
    for path in ("user/secrets.env", "user/profile.md", "user/glossary.md"):
        assert _ignored(path)
