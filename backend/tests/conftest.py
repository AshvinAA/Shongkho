"""
Shared pytest fixtures: an isolated per-test database + API client.

Isolation strategy:
  - Each test gets a FRESH SQLite file database (tmp_path), so schema and
    data never leak between tests. (A file DB is used instead of
    sqlite:///:memory: because SQLAlchemy connections each get their own
    empty in-memory DB — a shared file keeps one schema for all sessions.)
  - FastAPI's get_db dependency is overridden to hand out sessions bound
    to that same database file.
  - Authentication is exercised for real (no mocking of the auth logic):
    helpers register + log a user in, and the TestClient's cookie jar
    carries the session cookie on every request.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Make backend/ importable (tests live in backend/tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from main import app  # noqa: E402

# --- LLM env isolation -------------------------------------------------
# database.py load_dotenv()s backend/.env for the WHOLE test process.
# That would leak LLM_PROVIDER / GEMINI_API_KEY / LLM_MODEL into tests
# (some tests would hit the real local Ollama). Tests must be hermetic:
# scrub the LLM namespace; individual tests monkeypatch what they need.
for _var in list(os.environ):
    if _var in ("LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY",
                "LLM_BUDGET_SECONDS", "OLLAMA_URL"):
        del os.environ[_var]


@pytest.fixture()
def db_engine(tmp_path):
    """
    A fresh SQLite database file per test.

    Yields the engine; drops everything afterwards so the temp folder
    stays clean even on failures.
    """
    db_file = tmp_path / "test_shongkho.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})

    # Create the full schema exactly as production would.
    from models import Base
    Base.metadata.create_all(bind=engine)

    yield engine
    engine.dispose()
    if db_file.exists():
        db_file.unlink()


@pytest.fixture()
def db_session(db_engine):
    """A plain session for arranging test data directly via the ORM."""
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine, db_session):
    """
    TestClient wired to the isolated database.

    The get_db dependency is overridden so every request handled by the
    app uses a session bound to the same per-test SQLite file.
    """
    def _override_get_db():
        Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[database.get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------
# Helper: register + login via the real API
# ---------------------------------------------------------

def _register_and_login(client: TestClient, *, role: str, phone: str,
                        password: str = "secret123", name: str = None,
                        employer_id: int = None):
    """
    Register an account through POST /auth/register, then log in through
    POST /auth/login. Returns the register response JSON.

    The session cookie lands in the client's cookie jar automatically.
    """
    payload = {
        "name": name or f"{'Owner' if role == 'owner' else 'Employee'} {phone[-4:]}",
        "phone_number": phone,
        "password": password,
        "role": role,
    }
    if employer_id is not None:
        payload["employer_id"] = employer_id

    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, f"registration failed: {r.json()}"

    r = client.post(
        "/api/v1/auth/login",
        json={"phone_number": phone, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.json()}"
    return r.json()


@pytest.fixture()
def owner(client):
    """A logged-in store owner. Returns the login payload (user_id, role, name)."""
    return _register_and_login(client, role="owner", phone="01700000001", name="The Owner")


@pytest.fixture()
def employee(client, owner):
    """A logged-in employee working for `owner`."""
    owner_id = owner["user_id"]
    return _register_and_login(
        client, role="employee", phone="01700000002", name="Staff Guy", employer_id=owner_id
    )


@pytest.fixture()
def owner_client(client, owner):
    """
    A SECOND TestClient logged in as the owner.

    TestClient keeps one cookie jar per instance. This lets a test act as
    the employee through `client` while reading/writing owner-only data
    through `owner_client` — no login/logout dances inside the tests.
    """
    second = TestClient(app)
    r = second.post("/api/v1/auth/login", json={
        "phone_number": "01700000001", "password": "secret123",
    })
    assert r.status_code == 200, r.json()
    return second


@pytest.fixture()
def product(owner_client):
    """One product in stock (created by the owner through owner_client)."""
    r = owner_client.post("/api/v1/products/", json={
        "product_name": "Test Widget",
        "cost_price": 40.0,
        "retail_price": 60.0,
        "stock_quantity": 100,
        "category": "Gadgets",
    })
    assert r.status_code == 200, r.json()
    return r.json()


@pytest.fixture()
def customer(owner_client):
    """One customer registered by the owner."""
    r = owner_client.post("/api/v1/customers/", json={
        "name": "Walkin Watson",
        "phone_number": "01800000001",
    })
    assert r.status_code == 200, r.json()
    return r.json()
