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


def test_login_throttle_counts_each_visitor_behind_the_proxy():
    """Behind the company's proxy every request comes from the same place: one visitor's guessing must not lock out
    a colleague signing in from elsewhere, and a forged address header must not buy unlimited tries."""
    guesser = make_client()
    for _ in range(10):
        guesser.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "wrong"},
                     headers={"X-Forwarded-For": "81.10.20.30"})
    blocked = guesser.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "demo1234"},
                           headers={"X-Forwarded-For": "81.10.20.30"})
    assert blocked.status_code == 429
    anna = make_client().post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "demo1234"},
                              headers={"X-Forwarded-For": "62.40.1.2"})
    assert anna.status_code == 200

    # A new forged address each time: the limit per account still holds
    for i in range(50):
        guesser.post("/api/auth/login", json={"email": "lukas.schmid@example.com", "password": "wrong"},
                     headers={"X-Forwarded-For": f"81.10.21.{i + 1}"})
    late = make_client().post("/api/auth/login", json={"email": "lukas.schmid@example.com", "password": "demo1234"},
                              headers={"X-Forwarded-For": "62.40.1.3"})
    assert late.status_code == 429


def test_profile_cannot_change_role(anna):
    response = anna.patch("/api/profile", json={"job_title": "Team Lead", "role": "admin"})
    assert response.status_code == 200
    assert response.json()["job_title"] == "Team Lead"
    assert response.json()["role"] == "employee"


def test_change_password(anna):
    assert anna.post("/api/profile/password", json={"current_password": "x", "new_password": "newpassword1"}).status_code == 422
    assert anna.post("/api/profile/password", json={"current_password": "demo1234", "new_password": "newpassword1"}).status_code == 204
