import pyotp

from app.core.security import utcnow
from tests.conftest import PASSWORD, auth_headers, register


def test_register_login_me(client):
    out = register(client)
    assert out["user"]["email"] == "alice@example.com"
    r = client.get("/api/v1/auth/me", headers=auth_headers(out))
    assert r.status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": "ALICE@example.com", "password": PASSWORD})
    assert r.status_code == 200


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "password1234"})
    assert r.status_code == 422


def test_validation_errors_do_not_echo_password(client):
    r = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "SuperSecret-Value-99"})
    assert r.status_code == 422
    assert "SuperSecret" not in r.text


def test_generic_login_errors(client):
    register(client)
    bad_pw = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    no_user = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


def test_lockout_after_failed_attempts(client):
    register(client)
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    r = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 429


def test_unauthenticated_and_tampered_tokens(client):
    assert client.get("/api/v1/tasks").status_code == 401
    out = register(client)
    token = out["access_token"]
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    assert client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    # alg=none attack
    import base64
    import json
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = token.split(".")[1]
    assert client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {header}.{body}."}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    register(client)
    old_cookie = client.cookies.get("cos_rt")
    r1 = client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new_token = r1.json()["access_token"]
    # Replay the old refresh token -> whole family revoked
    client.cookies.clear()
    client.cookies.set("cos_rt", old_cookie)
    r2 = client.post("/api/v1/auth/refresh")
    assert r2.status_code == 401
    # Access token from the rotated session no longer works
    assert client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {new_token}"}).status_code == 401


def test_refresh_requires_csrf_header(client):
    register(client)
    r = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": ""})
    assert r.status_code == 403


def test_logout_revokes_access_token(client):
    out = register(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/tasks", headers=auth_headers(out)).status_code == 401


def test_mfa_flow(client):
    out = register(client)
    h = auth_headers(out)
    setup = client.post("/api/v1/auth/mfa/setup", headers=h).json()
    totp = pyotp.TOTP(setup["secret"])
    r = client.post("/api/v1/auth/mfa/enable", json={"code": totp.now()}, headers=h)
    assert r.status_code == 200
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10

    r = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "mfa_required"
    # next time-step code (current one was already used during enable -> replay protection)
    next_code = totp.at(utcnow().timestamp() + 30)
    r = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD,
                                                "mfa_code": next_code})
    assert r.status_code == 200
    # recovery code works exactly once
    body = {"email": "alice@example.com", "password": PASSWORD, "recovery_code": codes[0]}
    assert client.post("/api/v1/auth/login", json=body).status_code == 200
    assert client.post("/api/v1/auth/login", json=body).status_code == 401


def test_password_reset_flow(client, caplog):
    register(client)
    import logging
    caplog.set_level(logging.WARNING, logger="app.mailer")
    r = client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
    assert r.status_code == 202
    # unknown email -> identical response
    r2 = client.post("/api/v1/auth/password/forgot", json={"email": "ghost@example.com"})
    assert r2.json() == r.json()
    token = caplog.text.split("#token=")[1].split()[0]
    new_pw = "Brand-New-Passphrase-7"
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new_pw}).status_code == 204
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new_pw}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": new_pw}).status_code == 200


def test_security_headers(client):
    r = client.get("/api/v1/auth/me")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]


def test_sessions_list_and_revoke(client):
    out = register(client)
    h = auth_headers(out)
    sessions = client.get("/api/v1/auth/sessions", headers=h).json()
    assert len(sessions) == 1 and sessions[0]["current"]
    assert client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=h).status_code == 204
    assert client.get("/api/v1/auth/sessions", headers=h).status_code == 401
