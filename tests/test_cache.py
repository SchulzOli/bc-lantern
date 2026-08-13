from __future__ import annotations

from pathlib import Path

from bc_lantern.cache import JsonCacheStore


def test_json_cache_store_persists_namespaced_values(tmp_path: Path) -> None:
    first = JsonCacheStore(tmp_path)
    first.put("github/app-json", "acme", {"repositories": {"acme/one": {}}})

    second = JsonCacheStore(tmp_path)

    assert second.get("github/app-json", "acme") == {
        "repositories": {"acme/one": {}}
    }


def test_json_cache_store_keeps_features_isolated(tmp_path: Path) -> None:
    cache = JsonCacheStore(tmp_path)
    cache.put("github/app-json", "acme", {"value": "manifests"})
    cache.put("github/dependencies", "acme", {"value": "dependencies"})

    assert cache.get("github/app-json", "acme") == {"value": "manifests"}
    assert cache.get("github/dependencies", "acme") == {"value": "dependencies"}


def test_json_cache_store_can_invalidate_one_entry(tmp_path: Path) -> None:
    cache = JsonCacheStore(tmp_path)
    cache.put("github/app-json", "acme", {"value": 1})

    cache.delete("github/app-json", "acme")

    assert cache.get("github/app-json", "acme") is None
