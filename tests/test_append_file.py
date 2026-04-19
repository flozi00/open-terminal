import os

from fastapi.testclient import TestClient

os.environ.setdefault("OPEN_TERMINAL_API_KEY", "test-api-key")

from open_terminal.main import app


client = TestClient(app)
HEADERS = {"Authorization": "Bearer test-api-key"}


def test_append_file_appends_to_existing_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    response = client.post(
        "/files/append",
        headers=HEADERS,
        json={"path": str(path), "content": " world"},
    )

    assert response.status_code == 200
    assert response.json() == {"path": str(path), "size": len(" world".encode())}
    assert path.read_text(encoding="utf-8") == "hello world"


def test_append_file_creates_missing_file_and_parents(tmp_path):
    path = tmp_path / "nested" / "notes.txt"

    response = client.post(
        "/files/append",
        headers=HEADERS,
        json={"path": str(path), "content": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {"path": str(path), "size": len("hello".encode())}
    assert path.read_text(encoding="utf-8") == "hello"
