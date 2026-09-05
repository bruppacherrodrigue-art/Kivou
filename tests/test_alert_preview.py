from pathlib import Path


def test_versioned_weekly_alert_preview_is_a_complete_html_email() -> None:
    preview = Path("docs/previews/weekly-alert.html").read_text(encoding="utf-8")

    assert preview.startswith("<!doctype html>")
    assert "3 nouveaux signaux pour vous" in preview
    assert preview.count("<article") == 3
    assert "Pour vous" in preview
    assert "Se désinscrire des alertes" in preview
