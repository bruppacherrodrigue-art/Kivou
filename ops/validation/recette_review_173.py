"""Read-only staging acceptance. Usage: python recette_review_173.py OUTPUT_DIR."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("KIVOU_QA_BASE_URL", "https://staging.kivou.eu")
OUTPUT = Path(sys.argv[1])


def loaded(page, path, selector):
    page.goto(BASE + path, wait_until="domcontentloaded")
    expect(page.locator(selector).first).to_be_visible(timeout=20000)
    page.evaluate("document.fonts.ready")


def capture(page, label):
    page.screenshot(path=str(OUTPUT / f"{label}.png"), animations="disabled")


def companies(page, width, label):
    loaded(page, "/app/companies", "main table tbody tr button")
    table = page.locator("main table").first
    buttons = table.locator("tbody tr button")
    assert buttons.count() >= 2, "fixture: two companies required"
    first, second = buttons.nth(0).inner_text(), buttons.nth(1).inner_text()
    buttons.nth(0).click()
    panel = page.get_by_role("complementary", name=first, exact=True)
    expect(panel).to_be_visible()
    capture(page, label + "-companies")
    if width >= 900:
        left, right = table.bounding_box(), panel.bounding_box()
        assert left and right and right["x"] >= left["x"] + left["width"] - 1, "panel overlaps table"
        assert abs(right["width"] - 520) < 2, "panel must be 520px"
        assert table.locator("thead th").all_text_contents() == ["Entreprise", "Statut"]
        assert panel.evaluate("el => getComputedStyle(el).position") != "fixed"
        assert buttons.nth(1).evaluate("el => { const r=el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)); }"), "overlay intercepts company list"
        buttons.nth(1).click(timeout=5000)
        expect(page.get_by_role("complementary", name=second, exact=True)).to_be_visible()
        expect(table.locator("tr[aria-current=true]")).to_contain_text(second)
        capture(page, label + "-companies-switched")
    else:
        box = panel.bounding_box()
        assert box and abs(box["x"]) < 1 and abs(box["width"] - width) < 2
        assert not table.is_visible(), "company list visible with mobile sheet"
        panel.get_by_role("button", name="Fermer", exact=True).click()
        expect(table).to_be_visible()


def signals(page, width, label):
    loaded(page, "/app/signals?status=all&period=all", '[data-page="signals"] [data-signal-key] button')
    surface = page.locator('[data-page="signals"]')
    capture(page, label + "-signals")
    if width < 900:
        assert page.locator("table").count() == 0, "mobile table remains in DOM"
        cards = surface.locator("article[data-signal-key]")
        assert cards.count() > 0, "signal cards missing"
        for card in cards.all():
            assert card.locator(":scope > *").count() == 3, "card must have three rows"
            title, subject, meta = [card.locator(":scope > *").nth(i) for i in range(3)]
            assert title.evaluate("el => getComputedStyle(el).textOverflow") == "ellipsis"
            assert title.evaluate("el => getComputedStyle(el).whiteSpace") == "nowrap"
            assert subject.evaluate("el => getComputedStyle(el).webkitLineClamp") == "2"
            boxes = [el.bounding_box() for el in (title, subject, meta)]
            assert boxes[0]["y"] < boxes[1]["y"] < boxes[2]["y"], "card rows are not stacked"
            assert abs(boxes[0]["width"] - boxes[1]["width"]) < 2, "object not full width"
            assert card.evaluate("el => el.scrollWidth <= el.clientWidth"), "card overflow"
            match = meta.locator('[role="img"]')
            expect(match).to_have_count(1)
            assert match.bounding_box()["x"] > meta.bounding_box()["x"], "match not on right"
        if label.startswith("decouverte"):
            locked = surface.locator('article[data-locked="true"]').first
            expect(locked).to_be_visible()
            expect(locked).to_contain_text("Réservé aux offres Essentiel et Pro")
            expect(locked.locator("svg")).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "page overflow"
    surface.locator('[data-signal-key]:not([data-locked="true"]) button').first.click()
    drawer = page.locator("aside[data-signal-key]")
    expect(drawer).to_be_visible(timeout=15000)
    expect(drawer.get_by_role("heading", level=2)).not_to_be_empty()
    capture(page, label + "-drawer")


def zone(page, width, label):
    loaded(page, "/app/dashboard", '[data-page="today"] h1')
    response = page.request.get(BASE + "/dashboard")
    assert response.ok
    labels = response.json()["profile"]["zone_labels"]
    header = page.locator(".topbar")
    zone_text = header.locator('[data-profile-zones]')
    expect(zone_text).to_be_visible()
    expected = list(dict.fromkeys("France" if v.strip() == "FR" else v.strip() for v in labels if v.strip()))
    assert expected, "profile fixture has no zones"
    assert zone_text.inner_text() == ", ".join(expected), "mobile header differs from summary.profile.zone_labels"
    assert not re.search(r"\bFR\b", header.inner_text()), "FR in mobile header"
    capture(page, label + "-header")


def settings(page, width, label):
    loaded(page, "/app/settings", ".settings-main")
    expect(page.locator("#settings-plan-title")).not_to_contain_text("Chargement", timeout=20000)
    root = page.locator(".settings-main")
    capture(page, label + "-settings")
    assert not re.search(r"(?<!\S)—(?!\S)", root.inner_text()), "missing-value dash"
    assert "Tarif facturé absent" not in root.inner_text()
    for el in root.locator("h2, h3, nav a, dt, dd").all():
        family = el.evaluate("el => getComputedStyle(el).fontFamily").lower()
        assert not any(font in family for font in ("lora", "georgia", "times new roman")), f"serif: {family}"
    expect(root.locator('[data-ui="screen-header"]')).to_have_count(1)
    expect(root.locator('[data-ui="screen-segments"]')).to_have_count(1)
    assert root.locator('[data-ui="summary-row"]').count() >= 2
    root.get_by_role("link", name="Compte", exact=True).click()
    form = page.get_by_role("form", name="Informations principales")
    expect(form).to_be_visible()
    expect(form.get_by_label("Fuseau horaire")).to_have_count(0)
    capture(page, label + "-settings-profile")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/srv/kivou/playwright/chromium-1234/chrome-linux64/chrome")
        for account, email_key, password_key in (
            ("decouverte", "KIVOU_QA_DISCOVERY_EMAIL", "KIVOU_QA_DISCOVERY_PASSWORD"),
            ("essentiel", "KIVOU_QA_ESSENTIAL_EMAIL", "KIVOU_QA_PAYING_PASSWORD"),
        ):
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="fr-FR")
            page = context.new_page()
            page.goto(BASE + "/login")
            page.get_by_label("Adresse e-mail professionnelle").fill(os.environ[email_key])
            page.locator("#login-password").fill(os.environ[password_key])
            page.get_by_role("button", name="Se connecter", exact=True).click()
            page.wait_for_url("**/app/**")
            page.close()
            for width in (1440, 390):
                for check in (companies, signals, zone, settings):
                    if check == zone and width == 1440:
                        continue
                    page = context.new_page()
                    page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
                    label = f"{account}-{width}"
                    result = {"account": account, "width": width, "check": check.__name__}
                    try:
                        check(page, width, label)
                        result["status"] = "passed"
                    except (AssertionError, PlaywrightError) as error:
                        result.update(status="failed", error=str(error))
                        capture(page, label + "-" + check.__name__ + "-failed")
                    finally:
                        page.close()
                    results.append(result)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
            context.close()
        browser.close()
    (OUTPUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(result["status"] == "failed" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
