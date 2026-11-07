"""Reading a balance off a page by its label, on pages laid out the ways real sites do it."""

import glob
import os
from datetime import date

import pytest

from award_wallet import fetching
from award_wallet.providers import Expiration
from award_wallet.providers.american import American
from award_wallet.providers.american_express import AmericanExpress
from award_wallet.providers.chase import Chase
from award_wallet.providers.delta import Delta

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


def test_a_confirm_its_you_page_drawn_in_web_components_is_recognized(browser):
    page = browser.new_page()
    page.set_content(
        "<!doctype html><body><x-card></x-card><script>customElements.define('x-card', class extends HTMLElement {"
        " constructor() { super(); this.attachShadow({ mode: 'open' }).innerHTML ="
        " '<h1>Let’s make sure it’s you</h1><p>We’ll text a one-time code to your phone.</p>'; } });</script>"
    )
    assert "make sure" not in page.locator("body").inner_text()  # the page's plain text misses it
    assert fetching._asks_who_you_are(page)
    page.set_content("<!doctype html><body><h2>Rewards</h2><p>163,918 Ultimate Rewards points</p></body>")
    assert not fetching._asks_who_you_are(page)
    page.close()


@pytest.fixture
def read(browser):
    page = browser.new_page()

    def read(body: str, provider=None) -> int | None:
        page.set_content(f"<!doctype html><html><body>{body}</body></html>")
        return fetching.read_balance(page, provider or Chase())[0]

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


# American's account summary: award miles next to Loyalty Points (status), lifetime miles toward
# Million Miler, and card offers in miles. Only the award miles are the balance.
AA_OFFER = "<aside><p>Earn up to 60,000 miles with an AAdvantage<sup>®</sup> card</p></aside>"


def test_american_reads_award_miles_from_its_own_tile(read):
    tiles = (
        "<section><div class=tile><h3>Award miles</h3><p>48,210</p></div>"
        "<div class=tile><h3>Loyalty Points</h3><p>12,500</p></div>"
        "<div class=tile><h3>Million Miler<sup>™</sup> lifetime miles</h3><p>231,004</p></div></section>"
    )
    assert read(AA_OFFER + tiles, American()) == 48210


def test_american_reads_award_miles_from_a_list_of_numbers(read):
    summary = "<dl><dt>Award miles</dt><dd>48,210</dd><dt>Loyalty Points</dt><dd>12,500</dd></dl>"
    assert read(summary + AA_OFFER, American()) == 48210
    assert read("<p>Mileage balance: 48,210</p>" + AA_OFFER, American()) == 48210


def test_american_never_takes_an_offer_for_the_balance(read):
    assert read("<header>Hi, Rafael</header>" + AA_OFFER, American()) is None


# The real account summary (November 2026): the member card, the award miles with when they
# expire under them, and Loyalty Points, which reset on another date.
AA_SUMMARY = (
    "<div id=member-info-container-id><div class=member><h2>Rafael Gama</h2><p>AAdvantage® member</p>"
    "<p>AAdvantage® member since: Sep 19, 2007</p><p>Million Miler: 50,179 miles</p></div>"
    "<div class=miles><h3>Award miles balance</h3><p class=big>49,333</p><p>Award Miles</p>"
    "<a href='#'>Redeem miles</a><small>Miles expire on Jan 3, 2028</small></div>"
    "<div class=status><h3>AAdvantage® status</h3><p class=big>0</p><p>Loyalty Points</p>"
    "<p>Loyalty Points reset to zero March 1</p></div></div>"
)


def test_american_reads_the_balance_and_when_it_expires_from_the_real_summary(read, browser):
    assert read(AA_SUMMARY, American()) == 49333
    page = browser.new_page()
    page.set_content(f"<!doctype html><body>{AA_SUMMARY}</body>")
    assert fetching.read_expirations(page, American()) == [Expiration(date(2028, 1, 3))]
    page.close()


def test_american_finds_the_expiration_by_its_words_wherever_the_page_puts_it(browser):
    # A redesign that moves the date into another box, splits it across tags or writes it out
    # in full still gives the same date: the words find it, not where it sits.
    page = browser.new_page()
    for body in (
        "<table><tr><td>Your miles expire on</td><td><b>January 3, 2028</b></td></tr></table>",
        "<p>Award miles 49,333</p><footer><span>Miles will expire on</span> <span>01/03/2028</span></footer>",
        "<ul><li>Miles expire on Jan. 3, 2028</li></ul>",
    ):
        page.set_content(f"<!doctype html><body>{body}</body>")
        assert fetching.read_expirations(page, American()) == [Expiration(date(2028, 1, 3))], body
    for body in (
        "<p>Your miles won't expire while you have an AAdvantage® card</p>",
        "<p>Loyalty Points reset to zero March 1</p><p>Member since: Sep 19, 2007</p>",
        "<p>Miles expire on Foo 99, 2028</p>",
    ):
        page.set_content(f"<!doctype html><body>{body}</body>")
        assert fetching.read_expirations(page, American()) == [], body
    page.close()


# American Express shows the points next to pending points, points that come in once the bill is
# paid, points earned this year and card offers in points. Only the points you have are the balance.
AMEX_OFFER = "<aside><p>Earn 10,000 Membership Rewards<sup>®</sup> points after you spend $1,000</p></aside>"
AMEX_BUCKETS = (
    "<div><h4>Pending Points</h4><p>2,345</p></div>"
    "<div><h4>Points Available on Payment</h4><p>0</p></div>"
    "<div><h4>Points earned this year</h4><p>40,120</p></div>"
)


def test_amex_reads_the_membership_rewards_tile(read):
    home = (
        "<section><h3>Total Balance</h3><p>$1,234.56</p></section>"
        "<section><h3>Membership Rewards<sup>®</sup> Points</h3><p>97,481</p><a href='#'>View Rewards</a></section>"
    )
    assert read(AMEX_OFFER + home, AmericanExpress()) == 97481


def test_amex_reads_the_points_you_have_not_pending_points(read):
    for words in ("Available Points", "Points Balance", "Current Points Balance"):
        points = f"<div><h4>{words}</h4><p>97,481</p></div>"
        assert read(AMEX_BUCKETS + points, AmericanExpress()) == 97481
        assert read(points + AMEX_BUCKETS, AmericanExpress()) == 97481


def test_amex_reads_a_number_written_with_its_label(read):
    assert read("<p>97,481 Membership Rewards<sup>®</sup> points</p>" + AMEX_OFFER, AmericanExpress()) == 97481
    assert read("<p>Points Balance: 97,481</p>" + AMEX_BUCKETS, AmericanExpress()) == 97481


def test_amex_never_takes_pending_points_or_an_offer_for_the_balance(read):
    assert read(AMEX_OFFER + AMEX_BUCKETS, AmericanExpress()) is None
    note = "<p>Pending points are added to your Points Balance once your payment posts.<sup>1</sup></p>"
    assert read(note + AMEX_BUCKETS, AmericanExpress()) is None


def test_leaves_out_text_only_screen_readers_get(read):
    hidden = "position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0)"
    tile = (
        f"<section><h3>Membership Rewards® Points<span style='{hidden}'>, more about your points</span></h3>"
        "<p>97,481</p></section>"
    )
    assert read(tile, AmericanExpress()) == 97481


# Delta's SkyMiles overview: the miles you can spend, then Medallion Qualifying Dollars, pending and
# upcoming credit from booked trips, lifetime miles toward Million Miler, and card offers in miles.
DELTA_OFFER = "<aside><p>Earn 70,000 bonus miles with a Delta SkyMiles<sup>®</sup> card</p></aside>"
DELTA_STATUS = (
    "<div><h4>MQDs</h4><p>$3,250</p></div>"
    "<div><h4>Pending &amp; Upcoming</h4><p>2,140</p><p>Miles</p></div>"
    "<div><h4>Million Miler<sup>™</sup></h4><p>412,906</p><p>Lifetime Miles</p></div>"
)


def test_delta_reads_the_miles_you_can_spend(read):
    hero = "<header><p>61,370</p><p>Available Miles</p><a href='#'>Book with Miles</a></header>"
    assert read(DELTA_OFFER + hero + DELTA_STATUS, Delta()) == 61370
    hero = "<header><h2>Miles Available</h2><strong>61,370</strong></header>"
    assert read(DELTA_STATUS + hero, Delta()) == 61370


def test_delta_reads_a_number_written_with_its_label(read):
    assert read("<p>61,370 available miles</p>" + DELTA_STATUS, Delta()) == 61370
    assert read("<p>SkyMiles® Miles Balance: 61,370</p>" + DELTA_OFFER, Delta()) == 61370


def test_delta_never_takes_pending_lifetime_or_offer_miles_for_the_balance(read):
    assert read(DELTA_OFFER + DELTA_STATUS, Delta()) is None
