import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from milestash.models import BalanceSnapshot, BalanceSource, ExpirationLot, LoyaltyAccount
from milestash.providers import Expiration, all_providers
from milestash.services import accounts, balances

from conftest import link, post_form


def test_provider_picker_lists_every_program(client):
    page = client.get("/accounts/new").text
    for name in ("American Airlines", "American Express", "Delta Air Lines", "United Airlines", "Chase", "Capital One"):
        assert name in page


def test_the_empty_dashboard_names_every_program(client):
    page = client.get("/").text
    assert "Nothing here yet" in page
    assert (
        "Link American Airlines, American Express, Capital One, Chase, Delta Air Lines or United Airlines "
        "to see your balances side by side."
    ) in page


def test_unknown_provider_is_a_404(client):
    assert client.get("/accounts/new?provider=nope").status_code == 404


def test_login_is_stored_encrypted(client, app, db):
    account_id = link(client, "united", credential_username="MP123456", credential_password="hunter2-but-longer")

    account = db.get(LoyaltyAccount, account_id)
    assert account.label == "MileagePlus"
    assert b"hunter2-but-longer" not in account.credentials_encrypted
    assert b"MP123456" not in account.credentials_encrypted
    assert accounts.read_credentials(app.state.vault, account) == {
        "username": "MP123456",
        "password": "hunter2-but-longer",
    }
    page = client.get(f"/accounts/{account_id}").text
    assert "hunter2-but-longer" not in page
    assert "Login saved" in page


def test_programs_can_be_tracked_by_hand(client, db):
    account_id = link(client, "chase", label="Sapphire Preferred")
    account = db.get(LoyaltyAccount, account_id)
    assert account.credentials_encrypted is None
    assert account.label == "Sapphire Preferred"


def test_half_a_login_is_rejected(client):
    response = post_form(
        client,
        "/accounts/new",
        {"provider": "united", "credential_username": "MP123456"},
        token_from="/accounts/new?provider=united",
    )
    assert response.status_code == 400
    assert "Fill in every login field" in response.text


def test_manual_balance_shows_on_the_dashboard(client):
    account_id = link(client, "united")
    response = post_form(
        client,
        f"/accounts/{account_id}/balance",
        {"balance": "125,000"},
        token_from=f"/accounts/{account_id}",
    )
    assert "Balance saved." in response.text

    dashboard = client.get("/").text
    assert "125,000" in dashboard
    assert "MileagePlus miles don&#39;t expire." in dashboard


def test_expiration_is_shown(client):
    account_id = link(client, "chase")
    expires_on = date.today() + timedelta(days=30)
    post_form(
        client,
        f"/accounts/{account_id}/balance",
        {"balance": "80000", "expiring_amount": "5,000", "expires_on": expires_on.isoformat()},
        token_from=f"/accounts/{account_id}",
    )
    dashboard = client.get("/").text
    assert "5,000 points expire" in dashboard
    assert "in 30 days" in dashboard


def test_an_expiration_months_away_is_a_plain_line_without_an_alert(client):
    account_id = link(client, "chase")
    expires_on = date.today() + timedelta(days=200)
    post_form(
        client,
        f"/accounts/{account_id}/balance",
        {"balance": "80000", "expiring_amount": "5,000", "expires_on": expires_on.isoformat()},
        token_from=f"/accounts/{account_id}",
    )
    for page in (client.get("/").text, client.get(f"/accounts/{account_id}").text):
        assert "5,000 points expire on" in page
        assert "expiry-alert" not in page and " days)" not in page


def test_bad_balance_input_keeps_what_you_typed(client):
    account_id = link(client, "united")
    for data, message in (
        ({"balance": "lots"}, "whole number"),
        ({"balance": "-5"}, "whole number"),
        ({"balance": "100", "expiring_amount": "50"}, "Add the date"),
        ({"balance": "100", "expires_on": "2001-01-01"}, "already passed"),
        ({"balance": "100", "expiring_amount": "500", "expires_on": "2999-01-01"}, "at most the balance"),
    ):
        response = post_form(client, f"/accounts/{account_id}/balance", data, token_from=f"/accounts/{account_id}")
        assert response.status_code == 400, data
        assert message in response.text, data
        assert f'value="{data["balance"]}"' in response.text


def test_latest_snapshot_wins(client, db):
    account = db.get(LoyaltyAccount, link(client, "united"))
    now = datetime.now(UTC)
    balances.record_balance(db, account, balance=1, source=BalanceSource.MANUAL, captured_at=now - timedelta(days=2))
    balances.record_balance(db, account, balance=3, source=BalanceSource.MANUAL, captured_at=now)
    balances.record_balance(db, account, balance=2, source=BalanceSource.MANUAL, captured_at=now - timedelta(days=1))

    latest = balances.latest_snapshots(db, [account.id])
    assert latest[account.id].balance == 3
    assert latest[account.id].captured_at.tzinfo is not None
    assert [s.balance for s in balances.balance_history(db, account)] == [3, 2, 1]


def test_replacing_and_removing_the_login(client, app, db):
    account_id = link(client, "united", credential_username="old", credential_password="old-password")

    post_form(
        client,
        f"/accounts/{account_id}/login",
        {"credential_username": "new", "credential_password": "new-password"},
        token_from=f"/accounts/{account_id}",
    )
    db.expire_all()
    account = db.get(LoyaltyAccount, account_id)
    assert accounts.read_credentials(app.state.vault, account)["username"] == "new"

    response = post_form(client, f"/accounts/{account_id}/login", {}, token_from=f"/accounts/{account_id}")
    assert response.status_code == 400

    post_form(client, f"/accounts/{account_id}/login/remove", {}, token_from=f"/accounts/{account_id}")
    db.expire_all()
    assert db.get(LoyaltyAccount, account_id).credentials_encrypted is None


def test_removing_a_program_deletes_its_history(client, db):
    account_id = link(client, "chase")
    post_form(
        client,
        f"/accounts/{account_id}/balance",
        {"balance": "10", "expires_on": (date.today() + timedelta(days=5)).isoformat()},
        token_from=f"/accounts/{account_id}",
    )
    response = post_form(client, f"/accounts/{account_id}/delete", {}, token_from=f"/accounts/{account_id}")
    assert "Removed Ultimate Rewards." in response.text

    assert db.scalar(select(func.count()).select_from(LoyaltyAccount)) == 0
    assert db.scalar(select(func.count()).select_from(BalanceSnapshot)) == 0
    assert db.scalar(select(func.count()).select_from(ExpirationLot)) == 0


def test_rewards_links_open_each_program_site(client):
    account_id = link(client, "chase")
    post_form(client, f"/accounts/{account_id}/balance", {"balance": "1000"}, token_from=f"/accounts/{account_id}")
    for page in (client.get("/").text, client.get(f"/accounts/{account_id}").text):
        assert page.count('href="https://ultimaterewards.chase.com"') == 1
        assert 'target="_blank"' in page
        assert "<span>Use points</span>" in page


def test_bank_programs_list_their_transfer_partners_folded_away(client):
    chase = link(client, "chase")
    page = client.get(f"/accounts/{chase}").text
    assert '<details class="manual partners">' in page
    assert 'Transfer partners <span class="summary-count">10 airlines, 4 hotels</span>' in page
    assert "World of Hyatt" in page and "* World of Hyatt: 4:3 with Sapphire Preferred" in page
    # Airlines' own miles don't move anywhere.
    united = link(client, "united")
    assert "Transfer partners" not in client.get(f"/accounts/{united}").text


def test_transfer_partner_lists_are_well_formed():
    for provider in all_providers():
        names = [partner.name for partner in provider.transfer_partners]
        assert len(names) == len(set(names)), provider.key
        assert bool(names) == (provider.category == "bank"), provider.key
        for partner in provider.transfer_partners:
            assert partner.kind in ("airline", "hotel"), partner
            assert re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", partner.ratio), partner


def test_linking_starts_with_the_programs_own_name(client, db):
    assert 'name="label"' not in client.get("/accounts/new?provider=american").text
    account_id = link(client, "american")
    assert db.get(LoyaltyAccount, account_id).label == "AAdvantage"


def test_a_program_is_renamed_on_its_page_and_its_card_follows(client, db):
    account_id = link(client, "american", label="American Airlines")
    page = client.get(f"/accounts/{account_id}").text
    assert 'title="Double-click to rename">American Airlines</h1>' in page
    assert f'action="/accounts/{account_id}/name"' in page
    # The card only shows the name.
    assert f'action="/accounts/{account_id}/name"' not in client.get("/").text

    response = post_form(
        client,
        f"/accounts/{account_id}/name",
        {"label": "  AAdvantage  "},
        token_from=f"/accounts/{account_id}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/{account_id}"
    db.expire_all()
    assert db.get(LoyaltyAccount, account_id).label == "AAdvantage"
    assert f'href="/accounts/{account_id}">AAdvantage</a>' in client.get("/").text

    # An empty name is the program's own again, and a long one is cut to fit.
    page = f"/accounts/{account_id}"
    post_form(client, f"{page}/name", {"label": "Mine"}, token_from=page)
    post_form(client, f"{page}/name", {"label": " "}, token_from=page)
    db.expire_all()
    assert db.get(LoyaltyAccount, account_id).label == "AAdvantage"
    post_form(client, f"{page}/name", {"label": "x" * 300}, token_from=page)
    db.expire_all()
    assert db.get(LoyaltyAccount, account_id).label == "x" * 100


def test_renaming_needs_the_pages_token(client, db):
    account_id = link(client, "united")
    response = client.post(f"/accounts/{account_id}/name", data={"label": "Hacked"})
    assert response.status_code == 403
    db.expire_all()
    assert db.get(LoyaltyAccount, account_id).label == "MileagePlus"


def test_american_airlines_can_be_linked(client):
    page = client.get("/accounts/new").text
    assert "American Airlines" in page and "AAdvantage" in page
    form = client.get("/accounts/new?provider=american").text
    assert "AAdvantage number or username" in form
    account_id = link(client, "american", credential_username="12345678", credential_password="pw")
    assert "AAdvantage" in client.get(f"/accounts/{account_id}").text


def test_american_airlines_reads_award_miles_not_loyalty_points():
    from milestash.providers import get_provider

    american = get_provider("american")
    assert american.supports_fetch and american.unit == "miles"
    assert american.balance_url.startswith("https://www.aa.com/")


def test_american_express_can_be_linked(client):
    page = client.get("/accounts/new").text
    assert "American Express" in page and "Membership Rewards" in page
    form = client.get("/accounts/new?provider=amex").text
    assert "User ID" in form
    account_id = link(client, "amex", credential_username="amexuser", credential_password="pw")
    assert "Membership Rewards" in client.get(f"/accounts/{account_id}").text


def test_american_express_reads_membership_rewards_points():
    from milestash.providers import get_provider

    amex = get_provider("amex")
    assert amex.supports_fetch and amex.unit == "points"
    assert amex.balance_url.startswith("https://global.americanexpress.com/")


def test_delta_can_be_linked(client):
    page = client.get("/accounts/new").text
    assert "Delta Air Lines" in page and "SkyMiles" in page
    form = client.get("/accounts/new?provider=delta").text
    assert "SkyMiles number or username" in form
    account_id = link(client, "delta", credential_username="9012345678", credential_password="pw")
    assert "SkyMiles" in client.get(f"/accounts/{account_id}").text


def test_delta_reads_the_miles_you_can_spend():
    from milestash.providers import get_provider

    delta = get_provider("delta")
    assert delta.supports_fetch and delta.unit == "miles"
    assert delta.balance_url.startswith("https://www.delta.com/")


def _local_noon() -> datetime:
    return datetime.now(UTC).astimezone().replace(hour=12, minute=0, second=0, microsecond=0)


def test_history_keeps_changes_and_one_entry_a_day(client, db):
    account = db.get(LoyaltyAccount, link(client, "united"))
    noon = _local_noon()

    def seen(balance, when):
        balances.record_balance(db, account, balance=balance, source=BalanceSource.SYNC, captured_at=when)

    seen(100, noon - timedelta(days=2))
    seen(100, noon - timedelta(days=1))  # the same balance: nothing new
    seen(90, noon - timedelta(hours=2))  # a change today
    seen(80, noon - timedelta(hours=1))  # another change today takes its place
    seen(80, noon)

    stored = db.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id)).all()
    assert sorted(snapshot.balance for snapshot in stored) == [80, 100]
    history = balances.balance_history(db, account)
    assert [(s.balance, balances.local_day(s.captured_at)) for s in history] == [
        (80, noon.date()),
        (100, (noon - timedelta(days=2)).date()),
    ]


def test_history_from_older_versions_shows_each_change_once(client, db):
    # Before 0.7 every refresh added an entry, like four of 49,333 in one morning.
    account = db.get(LoyaltyAccount, link(client, "american"))
    noon = _local_noon()
    kept = [(noon - timedelta(days=2), 50000), (noon - timedelta(days=1), 49333)]
    kept += [(noon + timedelta(minutes=minutes), 49333) for minutes in (0, 2, 20, 22)]
    for when, balance in kept:
        db.add(BalanceSnapshot(account_id=account.id, balance=balance, unit="miles", source="sync", captured_at=when))
    db.commit()

    history = balances.balance_history(db, account)
    assert [(s.balance, balances.local_day(s.captured_at)) for s in history] == [
        (49333, (noon - timedelta(days=1)).date()),
        (50000, (noon - timedelta(days=2)).date()),
    ]
    assert balances.latest_snapshots(db, [account.id])[account.id].captured_at == noon + timedelta(minutes=22)


def test_refreshes_keep_the_expirations_you_entered(client, db):
    # Sites don't show when points expire, so the dates typed in by hand have to outlast refreshes.
    account = db.get(LoyaltyAccount, link(client, "chase"))
    noon = _local_noon()
    past, soon, later = (noon.date() + timedelta(days=days) for days in (-5, 30, 90))
    balances.record_balance(
        db,
        account,
        balance=80000,
        source=BalanceSource.MANUAL,
        expirations=[Expiration(past, 1000), Expiration(soon, 5000), Expiration(later)],
        captured_at=noon - timedelta(days=10),
    )

    def refresh(balance, when):
        balances.record_balance(db, account, balance=balance, source=BalanceSource.SYNC, captured_at=when)
        newest = balances.latest_snapshots(db, [account.id])[account.id]
        return [(lot.expires_on, lot.amount) for lot in newest.expirations]

    assert refresh(80000, noon - timedelta(days=9)) == [(past, 1000), (soon, 5000), (later, None)]
    # A date that went by is dropped, and no more can expire than the balance.
    assert refresh(3000, noon) == [(soon, 3000), (later, None)]
    assert "3,000 points expire" in client.get("/").text
    assert refresh(0, noon) == []

    # Entering the balance by hand without a date is how you clear one.
    balances.record_balance(
        db, account, balance=500, source=BalanceSource.MANUAL, expirations=[Expiration(soon)], captured_at=noon
    )
    balances.record_balance(db, account, balance=500, source=BalanceSource.MANUAL, captured_at=noon)
    assert refresh(700, noon) == []


def test_only_a_big_fall_is_held_back(client, db):
    account = db.get(LoyaltyAccount, link(client, "united"))
    assert balances.held_back_from(db, account, 0) is None  # nothing to compare with yet
    balances.record_balance(db, account, balance=80000, source=BalanceSource.SYNC)
    assert balances.held_back_from(db, account, 39999) == 80000
    assert balances.held_back_from(db, account, 40000) is None  # half is fine
    assert balances.held_back_from(db, account, 120000) is None
    balances.record_balance(db, account, balance=1500, source=BalanceSource.MANUAL)
    assert balances.held_back_from(db, account, 600) is None  # less than 1,000 fewer
    assert balances.held_back_from(db, account, 0) == 1500
