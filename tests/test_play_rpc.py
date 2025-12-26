from __future__ import annotations


def _rpc(db: object, *, req_id: int, method: str, params: dict | None = None) -> dict:
    import reos.ui_rpc_server as ui

    req: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    resp = ui._handle_jsonrpc_request(db, req)
    assert resp is not None
    return resp


def test_play_rpc_me_and_acts_defaults(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    # Keep test data out of the repo-local `.reos-data/`.
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    me_resp = _rpc(db, req_id=1, method="play/me/read")
    assert "result" in me_resp
    assert "markdown" in me_resp["result"]
    assert "Me" in str(me_resp["result"]["markdown"])

    acts_resp = _rpc(db, req_id=2, method="play/acts/list")
    result = acts_resp["result"]
    assert result["acts"] == []
    assert result["active_act_id"] is None


def test_play_rpc_set_active_unknown_act_is_invalid_params(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    resp = _rpc(db, req_id=1, method="play/acts/set_active", params={"act_id": "does-not-exist"})
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_play_rpc_create_scene_beat_and_kb_write_flow(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    create_act = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1", "notes": "n"})
    assert "result" in create_act
    act_id = create_act["result"]["created_act_id"]
    assert isinstance(act_id, str)
    assert create_act["result"]["acts"][0]["active"] is True

    create_scene = _rpc(
        db,
        req_id=2,
        method="play/scenes/create",
        params={
            "act_id": act_id,
            "title": "Scene 1",
            "intent": "ship",
            "status": "now",
            "time_horizon": "today",
            "notes": "scene-notes",
        },
    )
    scenes = create_scene["result"]["scenes"]
    assert len(scenes) == 1
    scene_id = scenes[0]["scene_id"]

    create_beat = _rpc(
        db,
        req_id=3,
        method="play/beats/create",
        params={"act_id": act_id, "scene_id": scene_id, "title": "Beat 1", "status": "todo"},
    )
    beats = create_beat["result"]["beats"]
    assert len(beats) == 1
    beat_id = beats[0]["beat_id"]
    assert isinstance(beat_id, str)

    preview = _rpc(
        db,
        req_id=4,
        method="play/kb/write_preview",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "beat_id": beat_id,
            "path": "kb.md",
            "text": "hello\n",
        },
    )["result"]
    assert "expected_sha256_current" in preview
    assert "sha256_new" in preview
    assert "diff" in preview

    applied = _rpc(
        db,
        req_id=5,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "beat_id": beat_id,
            "path": "kb.md",
            "text": "hello\n",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )["result"]
    assert applied["sha256_current"] == preview["sha256_new"]

    read_back = _rpc(
        db,
        req_id=6,
        method="play/kb/read",
        params={"act_id": act_id, "scene_id": scene_id, "beat_id": beat_id, "path": "kb.md"},
    )["result"]
    assert read_back["text"] == "hello\n"


def test_play_rpc_kb_rejects_path_traversal(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    act_id = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1"})["result"][
        "created_act_id"
    ]

    resp = _rpc(
        db,
        req_id=2,
        method="play/kb/write_preview",
        params={"act_id": act_id, "path": "../escape.md", "text": "nope"},
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_play_rpc_kb_apply_conflict_is_error(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    act_id = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1"})["result"][
        "created_act_id"
    ]

    preview = _rpc(
        db,
        req_id=2,
        method="play/kb/write_preview",
        params={"act_id": act_id, "path": "kb.md", "text": "one"},
    )["result"]
    _rpc(
        db,
        req_id=3,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "path": "kb.md",
            "text": "one",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )

    conflict = _rpc(
        db,
        req_id=4,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "path": "kb.md",
            "text": "two",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )
    assert "error" in conflict
    assert conflict["error"]["code"] == -32009
