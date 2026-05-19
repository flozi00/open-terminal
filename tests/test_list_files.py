import os

from fastapi.testclient import TestClient

os.environ.setdefault("OPEN_TERMINAL_API_KEY", "test-api-key")

from open_terminal.main import app


client = TestClient(app)
HEADERS = {"Authorization": "Bearer test-api-key"}


def test_list_files_returns_home_by_default(tmp_path):
    """With no path argument the endpoint lists the server's home directory."""
    response = client.get("/files/list", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "dir" in data
    assert "entries" in data


def test_list_files_respects_path_parameter(tmp_path):
    """The path parameter must be honoured, not silently ignored."""
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")

    response = client.get(
        "/files/list",
        headers=HEADERS,
        params={"path": str(tmp_path)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dir"] == str(tmp_path)
    names = [e["name"] for e in data["entries"]]
    assert "alpha.txt" in names
    assert "beta.txt" in names


def test_list_files_404_on_missing_path(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    response = client.get(
        "/files/list",
        headers=HEADERS,
        params={"path": missing},
    )
    assert response.status_code == 404
