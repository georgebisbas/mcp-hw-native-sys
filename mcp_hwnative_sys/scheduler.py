"""Lookup for the simpler scheduler catalog."""

from __future__ import annotations

import json
from typing import Any

from mcp_hwnative_sys.paths import project_root


def scheduler_index_path():
    return project_root() / "config" / "simpler_scheduler.json"


def load_scheduler_index() -> dict[str, Any]:
    path = scheduler_index_path()
    if not path.exists():
        return {
            "warning": f"Missing {path.name}. Run tools/build_simpler_scheduler_index.py.",
            "levels": [],
            "engines": [],
            "implementations": [],
            "cards": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def scheduler_cards() -> dict[str, Any]:
    cards = load_scheduler_index().get("cards", {})
    return cards if isinstance(cards, dict) else {}


def _fold_scheduler_name(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("_", "").replace("-", "").replace(".", "").replace("/", "")


def explain_scheduler_impl(name: str) -> dict[str, Any]:
    index = load_scheduler_index()
    if index.get("warning") and not index.get("cards"):
        raise ValueError(index["warning"])

    needle = _fold_scheduler_name(name)
    if not needle:
        raise ValueError("name cannot be empty")

    cards: dict[str, Any] = index.get("cards", {})
    matches: list[dict[str, Any]] = []
    for key, card in cards.items():
        hay = f"{key} {card.get('one_liner', '')} {' '.join(card.get('paths', []))}"
        if needle in _fold_scheduler_name(hay):
            matches.append({"name": key, **{k: card.get(k) for k in ("layer", "kind", "one_liner", "paths", "docs_canonical")}})

    if not matches:
        available = ", ".join(sorted(cards)[:12])
        raise ValueError(f"Unknown scheduler '{name}'. Examples: {available}")
    if len(matches) == 1:
        return matches[0]
    exact = [item for item in matches if _fold_scheduler_name(item["name"]).endswith(needle)]
    if len(exact) == 1:
        return exact[0]
    return {"ambiguous": True, "query": name, "candidates": matches[:20]}
