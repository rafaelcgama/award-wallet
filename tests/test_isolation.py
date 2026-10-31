"""People sharing one Award Wallet must never see or change each other's programs."""

from conftest import link, post_form, register


def test_other_peoples_programs_are_invisible(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as alice, TestClient(app) as bob:
        register(alice, "alice@example.com", "Alice")
        register(bob, "bob@example.com", "Bob")

        account_id = link(alice, "united", label="Alice's United")
        post_form(alice, f"/accounts/{account_id}/balance", {"balance": "777"}, token_from=f"/accounts/{account_id}")

        assert "Alice&#39;s United" not in bob.get("/").text
        assert bob.get(f"/accounts/{account_id}").status_code == 404

        for path, data in (
            (f"/accounts/{account_id}/balance", {"balance": "1"}),
            (f"/accounts/{account_id}/login", {"credential_username": "x", "credential_password": "y"}),
            (f"/accounts/{account_id}/login/remove", {}),
            (f"/accounts/{account_id}/delete", {}),
        ):
            assert post_form(bob, path, data, token_from="/").status_code == 404, path

        page = alice.get(f"/accounts/{account_id}").text
        assert "777" in page
        assert "Login saved" not in page and "Entered by hand" in page
