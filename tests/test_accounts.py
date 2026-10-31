from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from award_wallet.models import BalanceSnapshot, BalanceSource, ExpirationLot, LoyaltyAccount
from award_wallet.services import accounts, balances

from conftest import link, post_form, register


def test_provider_picker_lists_the_three_programs(client):
    register(client)
    page = client.get("/accounts/new").text
    for name in ("United Airlines", "Chase", "Capital One"):
        assert name in page


def test_unknown_provider_is_a_404(client):
    register(client)
    assert client.get("/accounts/new?provider=nope").status_code == 404


def test_login_is_stored_encrypted(client, app, db):
    register(client)
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
    register(client)
    account_id = link(client, "chase", label="Sapphire Preferred")
    account = db.get(LoyaltyAccount, account_id)
    assert account.credentials_encrypted is None
    assert account.label == "Sapphire Preferred"


def test_half_a_login_is_rejected(client):
    register(client)
    response = post_form(
        client,
        "/accounts/new",
        {"provider": "united", "credential_username": "MP123456"},
        token_from="/accounts/new?provider=united",
    )
    assert response.status_code == 400
    assert "Fill in every login field" in response.text


def test_manual_balance_shows_on_the_dashboard(client):
    register(client)
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
    register(client)
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


def test_bad_balance_input_keeps_what_you_typed(client):
    register(client)
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
    register(client)
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
    register(client)
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
    register(client)
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
    register(client)
    account_id = link(client, "chase")
    post_form(client, f"/accounts/{account_id}/balance", {"balance": "1000"}, token_from=f"/accounts/{account_id}")
    for page in (client.get("/").text, client.get(f"/accounts/{account_id}").text):
        assert page.count('href="https://ultimaterewards.chase.com"') == 2
        assert 'target="_blank"' in page
