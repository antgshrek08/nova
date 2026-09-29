"""The served app (/app) is rechecked on every open; its hashed assets are cached."""
from fastapi.testclient import TestClient

from app import main


def test_page_is_rechecked_and_assets_are_cached():
    if not main._FRONTEND_DIST.is_dir():
        return
    client = TestClient(main.app)
    page = client.get("/app/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    asset = next((main._FRONTEND_DIST / "assets").glob("*.js")).name
    assert "immutable" in client.get(f"/app/assets/{asset}").headers["cache-control"]
