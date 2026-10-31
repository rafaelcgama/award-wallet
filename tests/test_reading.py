"""Reading a balance off a page by its label, on pages laid out the ways real sites do it."""

import glob
import os

import pytest

from award_wallet import fetching
from award_wallet.providers.chase import Chase

CHROME = os.environ.get("AW_BROWSER_PATH") or next(
    iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None
)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no browser")

# The Rewards box on Chase's dashboard: a United card's miles, then the Ultimate Rewards points.
ROW = "<a class=row><img alt=''><div class=amount>{number}</div><div class=name>{name}</div></a>"
MILES, POINTS = "MileagePlus<sup>®</sup> Miles", "Ultimate Rewards<sup>®</sup> points"


def rewards_box(*rows: str) -> str:
    return f"<section><h2>Rewards</h2>{''.join(rows)}<a href='#'>See disclosures</a></section>"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME)
        yield browser
        browser.close()


@pytest.fixture
def read(browser):
    page = browser.new_page()

    def read(body: str) -> int | None:
        page.set_content(f"<!doctype html><html><body>{body}</body></html>")
        return fetching.read_balance(page, Chase())[0]

    yield read
    page.close()


def test_reads_the_points_not_the_miles_next_to_them(read):
    box = rewards_box(ROW.format(number="94,027", name=MILES), ROW.format(number="163,918", name=POINTS))
    assert read(box) == 163918


def test_reads_the_points_when_the_name_comes_before_the_number(read):
    row = "<a class=row><div>{name}</div><div>{number}</div></a>"
    box = rewards_box(row.format(number="94,027", name=MILES), row.format(number="163,918", name=POINTS))
    assert read(box) == 163918


def test_reads_inside_web_components(read):
    # The number is drawn by the component itself, so it isn't in the page's plain text.
    component = """
      <script>
        customElements.define("reward-row", class extends HTMLElement {
          connectedCallback() {
            const root = this.attachShadow({ mode: "open" });
            root.innerHTML = `<div><strong>${this.getAttribute("amount")}</strong><p><slot></slot></p></div>`;
          }
        });
      </script>
    """
    box = rewards_box(
        f"<reward-row amount='94,027'>{MILES}</reward-row>", f"<reward-row amount='163,918'>{POINTS}</reward-row>"
    )
    assert read(component + box) == 163918


def test_reads_a_number_written_with_its_label(read):
    assert read("<p>Ultimate Rewards® points: 163,918</p>") == 163918
    assert read("<p><b>163,918</b> Ultimate Rewards® points available</p>") == 163918


def test_ignores_numbers_in_sentences_and_hidden_copies(read):
    page = (
        "<p>Earn 5 Ultimate Rewards points per $1 on travel.</p>"
        "<div style='display:none'><span>1</span><span>Ultimate Rewards points</span></div>"
        + rewards_box(ROW.format(number="163,918", name=POINTS))
    )
    assert read(page) == 163918


def test_gives_up_rather_than_guess(read):
    # No box of its own for each program: either number could be the points.
    flat = f"<div><span>{MILES}</span><span>94,027</span><span>{POINTS}</span><span>163,918</span></div>"
    assert read(flat) is None
    # Still loading.
    assert read(rewards_box(f"<a class=row><div class=amount></div><div>{POINTS}</div></a>")) is None
    assert read("<p>Welcome back</p>") is None
