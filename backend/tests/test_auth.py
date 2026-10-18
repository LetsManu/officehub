from conftest import make_client


def test_login_and_me(anna):
    me = anna.get("/api/auth/me").json()
    assert me["first_name"] == "Anna"
    assert me["role"] == "employee"


def test_wrong_password_is_rejected():
    client = make_client()
    response = client.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_requires_login():
    assert make_client().get("/api/requests").status_code == 401


def test_logout_ends_session(anna):
    assert anna.post("/api/auth/logout").status_code == 204
    assert anna.get("/api/auth/me").status_code == 401


def test_state_change_requires_csrf_header(anna):
    response = anna.post("/api/auth/logout", headers={"X-Requested-With": ""})
    assert response.status_code == 403


def test_login_throttle():
    client = make_client()
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "wrong"})
    response = client.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "demo1234"})
    assert response.status_code == 429


def test_profile_cannot_change_role(anna):
    response = anna.patch("/api/profile", json={"job_title": "Team Lead", "role": "admin"})
    assert response.status_code == 200
    assert response.json()["job_title"] == "Team Lead"
    assert response.json()["role"] == "employee"


def test_change_password(anna):
    assert anna.post("/api/profile/password", json={"current_password": "x", "new_password": "newpassword1"}).status_code == 422
    assert anna.post("/api/profile/password", json={"current_password": "demo1234", "new_password": "newpassword1"}).status_code == 204
