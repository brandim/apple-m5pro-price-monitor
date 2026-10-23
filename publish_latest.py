"""Publish a small, validated, public-safe snapshot of the latest price check."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from price_check import HISTORY, SHANGHAI, URL, verify

PRODUCT = "14 英寸 MacBook Pro (M5)"
CONFIGURATION = {
    "size": "14 英寸",
    "chip": "Apple M5",
    "cpu_cores": 10,
    "gpu_cores": 10,
    "color": "深空黑色",
    "display": "标准显示屏",
    "memory_gb": 24,
    "storage_tb": 1,
    "power_adapter": "70W USB-C",
    "keyboard": "中文（拼音）",
    "market": "中国大陆普通零售",
}
FIELDS = {
    "product", "configuration", "verified", "price_cny", "checked_at",
    "previous_verified_price_cny", "price_change_cny", "source_url", "error",
}


def read_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    records = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [item for item in records if item.get("verified") is True and item.get("url") == URL]


def result_path(pointer: Path | None, direct: Path | None) -> Path | None:
    if direct:
        return direct
    if pointer and pointer.is_file():
        value = pointer.read_text(encoding="utf-8").strip()
        return Path(value) if value else None
    return None


def checked_at(result: dict | None) -> str:
    value = result.get("queried_at") if isinstance(result, dict) else None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is not None:
            return stamp.astimezone(SHANGHAI).isoformat()
    except (TypeError, ValueError):
        pass
    return datetime.now(SHANGHAI).isoformat()


def verified_evidence(result: dict, path: Path) -> bool:
    """Recheck the rendered DOM, selected configuration, and one-time total."""
    try:
        if (result.get("url") != URL or result.get("final_url") != URL
                or result.get("navigation_status") != 200
                or result.get("browser_started") is not True
                or result.get("verified") is not True
                or type(result.get("price_cny")) is not int
                or result["price_cny"] <= 0):
            return False
        if not (path.parent / "page.png").is_file():
            return False
        dom = json.loads((path.parent / "dom.json").read_text(encoding="utf-8"))
        if dom.get("url") != URL:
            return False
        checks, price, error = verify(dom, result["keyboard"])
        return error is None and price == result["price_cny"] and all(
            value for key, value in checks.items()
            if key not in ("apple_selected_state", "summary_field_checks")
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False


def validate_latest(data: dict, evidence_path: Path | None = None) -> None:
    if set(data) != FIELDS or data["product"] != PRODUCT or data["configuration"] != CONFIGURATION:
        raise ValueError("public JSON has unexpected fields or configuration")
    if data["source_url"] != URL or type(data["verified"]) is not bool:
        raise ValueError("public JSON has an invalid source or status")
    stamp = datetime.fromisoformat(data["checked_at"])
    if stamp.tzinfo is None:
        raise ValueError("checked_at must include a timezone")
    previous = data["previous_verified_price_cny"]
    if previous is not None and (type(previous) is not int or previous <= 0):
        raise ValueError("invalid previous price")
    if data["verified"]:
        if (type(data["price_cny"]) is not int or data["price_cny"] <= 0
                or data["error"] is not None
                or data["price_change_cny"] != (
                    data["price_cny"] - previous if previous is not None else None)):
            raise ValueError("verified price fields are inconsistent")
        if evidence_path is None:
            raise ValueError("verified publication requires browser evidence")
        result = json.loads(evidence_path.read_text(encoding="utf-8"))
        if (not verified_evidence(result, evidence_path)
                or data["price_cny"] != result["price_cny"]
                or data["checked_at"] != checked_at(result)):
            raise ValueError("verified publication does not match browser evidence")
    elif (data["price_cny"] is not None or data["price_change_cny"] is not None
          or not isinstance(data["error"], str) or not data["error"]):
        raise ValueError("failed checks must not expose a current price")


def build(path: Path | None, output: Path) -> dict:
    result = None
    if path and path.is_file():
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    history = read_history()
    current = history[-1] if history else None
    latest = {
        "product": PRODUCT,
        "configuration": CONFIGURATION,
        "verified": False,
        "price_cny": None,
        "checked_at": checked_at(result),
        "previous_verified_price_cny": current["price_cny"] if current else None,
        "price_change_cny": None,
        "source_url": URL,
        "error": "query_did_not_run" if result is None else "query_unverified",
    }
    if isinstance(result, dict) and result.get("verified") is True:
        if path and verified_evidence(result, path):
            same_run = current and current.get("queried_at") == result.get("queried_at")
            if same_run and current.get("price_cny") != result["price_cny"]:
                latest["error"] = "history_conflict"
            else:
                previous = history[-2] if same_run and len(history) > 1 else (None if same_run else current)
                old_price = previous["price_cny"] if previous else None
                price = result["price_cny"]
                latest.update(verified=True, price_cny=price,
                              previous_verified_price_cny=old_price,
                              price_change_cny=price - old_price if old_price is not None else None,
                              error=None)
                if not same_run:
                    record = {"queried_at": latest["checked_at"], "url": URL,
                              "verified": True, "currency": "CNY", "price_cny": price,
                              "previous_verified_price_cny": old_price,
                              "price_change_cny": latest["price_change_cny"]}
                    with HISTORY.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            latest["error"] = "evidence_validation_failed"
    elif isinstance(result, dict) and result.get("browser_started") is not True:
        latest["error"] = "browser_unavailable"

    validate_latest(latest, path if latest["verified"] else None)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return latest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument("--result-pointer", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--output", type=Path, default=Path("latest-price.json"))
    args = parser.parse_args()
    path = result_path(args.result_pointer, args.result)
    if args.command == "build":
        data = build(path, args.output)
    else:
        data = json.loads(args.output.read_text(encoding="utf-8"))
        validate_latest(data, path if data.get("verified") is True else None)
    print(json.dumps({"verified": data["verified"], "price_cny": data["price_cny"],
                      "checked_at": data["checked_at"], "error": data["error"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
