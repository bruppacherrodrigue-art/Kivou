"""Recette staging de finition #173.

Le même runner est exécuté contre la release avant puis après correction.
"""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


BASE_URL = os.environ.get("KIVOU_QA_BASE_URL", "https://staging.kivou.eu")
BROWSER = os.environ.get(
    "KIVOU_PLAYWRIGHT_EXECUTABLE",
    "/srv/kivou/playwright/chromium-1234/chrome-linux64/chrome",
)
CAPTURES = Path(os.environ.get("KIVOU_QA_CAPTURE_DIR", "/tmp/kivou-qa-captures"))
ACCOUNTS = (
    (os.environ["KIVOU_QA_DISCOVERY_EMAIL"], os.environ["KIVOU_QA_DISCOVERY_PASSWORD"], "decouverte"),
    (os.environ["KIVOU_QA_ESSENTIAL_EMAIL"], os.environ["KIVOU_QA_PAYING_PASSWORD"], "essentiel"),
)


def login(page: Page, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Adresse e-mail professionnelle").fill(email)
    page.get_by_role("textbox", name="Mot de passe").fill(password)
    page.get_by_role("button", name="Se connecter").click()
    page.wait_for_url("**/app/**")


def assert_needs_block_is_status_driven(page: Page) -> None:
    def hide_statuses(route):
        response = route.fetch()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("analysis"), dict):
            for need in payload["analysis"].get("plausible_needs", {}).get("items", []):
                need["timing_status"] = None
                need["quantity_status"] = None
        route.fulfill(response=response, json=payload)

    page.route("**/signals/**", hide_statuses)
    page.goto(f"{BASE_URL}/app/signals")
    page.wait_for_load_state("networkidle")
    signal = page.locator("[data-signal-key]").first
    if signal.count():
        signal.click()
        page.get_by_role("complementary").last.wait_for()
    assert page.get_by_text("Ce que le titulaire va devoir faire", exact=True).count() == 0


def assert_mobile_feed(page: Page) -> None:
    page.goto(f"{BASE_URL}/app/signals")
    page.wait_for_load_state("networkidle")
    assert page.locator("table").count() == 0
    assert page.locator("[data-signal-key]").count() > 0
    assert page.locator("body").evaluate("el => el.scrollWidth <= window.innerWidth")
    for card in page.locator("[data-signal-key]").all():
        assert card.evaluate("el => el.scrollWidth <= el.clientWidth"), "mot coupé dans la carte"


def assert_companies_panel(page: Page) -> None:
    page.goto(f"{BASE_URL}/app/companies")
    page.wait_for_load_state("networkidle")
    if page.locator("tbody tr").count():
        page.locator("tbody tr").first.click()
        panel = page.locator("aside").last
        panel.wait_for()
        table = page.locator("table").first
        panel_box = panel.bounding_box()
        table_box = table.bounding_box()
        assert panel_box and table_box and panel_box["x"] >= table_box["x"] + table_box["width"]
        assert page.locator("thead th").all_text_contents() == ["Entreprise", "Statut"]
        assert page.locator("aside").last.evaluate("el => getComputedStyle(el).position") != "fixed"


def assert_settings_and_zone(page: Page) -> None:
    page.goto(f"{BASE_URL}/app/settings")
    page.wait_for_load_state("networkidle")
    body = page.locator("body").inner_text()
    assert "—" not in body
    assert "Tarif facturé absent" not in body
    for heading in page.locator(".settings-main h2, .settings-main h3").all():
        family = heading.evaluate("el => getComputedStyle(el).fontFamily").lower()
        assert not any(font in family for font in ("lora", "georgia", "times new roman")), f"police serif: {family}"

    page.goto(f"{BASE_URL}/app/dashboard")
    page.wait_for_load_state("networkidle")
    assert "FR" not in page.locator("body").inner_text()


def main() -> int:
    CAPTURES.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=BROWSER)
        for email, password, account in ACCOUNTS:
            for width, label in ((1440, "desktop"), (390, "mobile")):
                page = browser.new_page(viewport={"width": width, "height": 900})
                try:
                    login(page, email, password)
                    if width < 900:
                        assert_mobile_feed(page)
                    else:
                        assert_companies_panel(page)
                    assert_settings_and_zone(page)
                    if width >= 900:
                        assert_needs_block_is_status_driven(page)
                    page.screenshot(path=str(CAPTURES / f"{account}-{label}.png"), full_page=True)
                except Exception as error:  # noqa: BLE001 - report every account/viewport
                    failures.append(f"{account}:{label}:{type(error).__name__}:{error}")
                finally:
                    page.close()
        browser.close()
    if failures:
        print("FAILURES")
        print("\n".join(failures))
        return 1
    print("PLAYWRIGHT_FINITION_GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
