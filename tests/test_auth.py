from conftest import PASSWORD, csrf_token, post_form, register


def test_dashboard_requires_sign_in(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_deep_link_returns_after_sign_in(client):
    response = client.get("/accounts/new", follow_redirects=False)
    assert response.headers["location"] == "/login?next=%2Faccounts%2Fnew"


def test_register_signs_you_in(client):
    response = register(client)
    assert "Your points" in response.text
    assert "Rafael" in response.text


def test_sign_out_and_back_in(client):
    register(client)
    response = post_form(client, "/logout", {}, token_from="/", follow_redirects=False)
    assert response.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303

    response = post_form(client, "/login", {"email": "RAFAEL@example.com ", "password": PASSWORD})
    assert response.status_code == 200
    assert "Your points" in response.text


def test_wrong_password(client):
    register(client)
    post_form(client, "/logout", {}, token_from="/")
    response = post_form(client, "/login", {"email": "rafael@example.com", "password": "wrong password"})
    assert response.status_code == 400
    assert "don&#39;t match" in response.text


def test_unknown_email(client):
    response = post_form(client, "/login", {"email": "nobody@example.com", "password": PASSWORD})
    assert response.status_code == 400


def test_duplicate_email_and_weak_password(client):
    register(client)
    post_form(client, "/logout", {}, token_from="/")
    for email, password, message in (
        ("rafael@example.com", PASSWORD, "already exists"),
        ("new@example.com", "short", "at least 10 characters"),
        ("not-an-email", PASSWORD, "valid email"),
    ):
        response = post_form(client, "/register", {"email": email, "password": password}, token_from="/register")
        assert response.status_code == 400
        assert message in response.text


def test_forms_need_their_token(client):
    response = client.post("/register", data={"email": "x@example.com", "password": PASSWORD})
    assert response.status_code == 403
    response = client.post("/register", data={"csrf_token": "forged", "email": "x@example.com", "password": PASSWORD})
    assert response.status_code == 403


def test_sign_in_rotates_the_session_token(client):
    before = csrf_token(client, "/register")
    register(client)
    assert csrf_token(client, "/") != before


def test_next_cannot_leave_the_site(client):
    register(client)
    post_form(client, "/logout", {}, token_from="/")
    response = post_form(
        client,
        "/login",
        {"email": "rafael@example.com", "password": PASSWORD, "next": "//evil.example"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_session_for_a_deleted_user_falls_back_to_sign_in(client, db):
    from award_wallet.models import User

    register(client)
    db.delete(db.query(User).one())
    db.commit()

    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/login", follow_redirects=False).status_code == 200


def test_signup_can_be_turned_off(settings):
    from fastapi.testclient import TestClient

    from award_wallet.web import create_app

    closed = settings.model_copy(update={"allow_signup": False})
    with TestClient(create_app(closed)) as client:
        assert client.get("/register").status_code == 403
        assert "Create an account" not in client.get("/login").text
