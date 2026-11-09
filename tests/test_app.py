import time

from fastapi.testclient import TestClient
from PIL import Image

from photo_upscaler import engine, server
from conftest import FAST_MODEL, photo


def wait_idle(client, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        q = client.get("/api/queue").json()
        if not q["running"]:
            return q
        time.sleep(0.05)
    raise AssertionError("queue never finished")


def test_queue_and_viewer_api(tmp_path, fake_engine, monkeypatch):
    monkeypatch.setattr(engine, "available_models",
                        lambda: [engine.Model(FAST_MODEL, "Fast", "d", 4, "fast", "CC-BY-4.0")])
    server.queue.jobs.clear()
    folder = tmp_path / "shoot"
    folder.mkdir()
    for i in range(3):
        photo(64, 48, seed=i).save(folder / f"img{i}.jpg")
    (folder / "notes.txt").write_text("not a photo")
    c = TestClient(server.app)

    assert c.get("/").status_code == 200
    assert c.get("/api/models").json()[0]["id"] == FAST_MODEL
    assert c.post("/api/add", json={"paths": [str(folder)]}).json()["added"] == 3
    assert c.post("/api/add", json={"paths": [str(folder / "img0.jpg")]}).json()["added"] == 0  # no duplicates

    r = c.post("/api/start", json={"model": FAST_MODEL, "scale": 2})
    assert r.status_code == 200
    q = wait_idle(c)
    assert [j["status"] for j in q["jobs"]] == ["done"] * 3
    j = q["jobs"][0]
    assert j["out_size"] == [128, 96] and "img0.jpg: 64x48 -> 128x96" in j["log"]
    assert Image.open(j["out_path"]).size == (128, 96)

    jid = j["id"]
    for which in ("before", "after"):
        im = c.get(f"/api/preview/{jid}?which={which}&w=100&h=100")
        assert im.status_code == 200 and im.headers["content-type"] == "image/jpeg"
        cr = c.get(f"/api/crop/{jid}?which={which}&x=10&y=10&w=50&h=40&zoom=2")
        from io import BytesIO
        assert Image.open(BytesIO(cr.content)).size == (100, 80)
    assert c.get(f"/api/thumb/{jid}").status_code == 200

    bad = c.post("/api/start", json={"model": FAST_MODEL, "mode": "long_edge", "long_edge": 0})
    assert bad.status_code == 400 and "long edge" in bad.json()["detail"]
    c.post("/api/clear", json={})
    assert c.get("/api/queue").json()["jobs"] == []
