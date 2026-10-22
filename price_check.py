"""Collect an evidence-backed retail price from Apple's configured purchase page."""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

URL = (
    "https://www.apple.com.cn/shop/buy-mac/macbook-pro/"
    "14-inch-space-black-standard-display-apple-m5-chip-10-core-cpu-"
    "10-core-gpu-24gb-memory-1tb-storage"
)
ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "price_history.jsonl"
SHANGHAI = ZoneInfo("Asia/Shanghai")
PRICE_RE = re.compile(r"(?:[¥￥]\s*|RMB\s*)([\d,]+)(?:\.00)?")
EXPECTED = {
    "size": r"14\s*(?:英寸|吋|inch)",
    "chip": r"M5\s*(?:芯片|chip)",
    "cpu": r"10\s*核\s*(?:CPU|中央处理器)|10.core\s*CPU",
    "gpu": r"10\s*核\s*(?:GPU|图形处理器)|10.core\s*GPU",
    "color": r"深空黑|Space Black",
    "display": r"标准显示屏|Standard Display",
    "memory": r"24\s*GB|24GB",
    "storage": r"1\s*TB|1TB",
    "adapter": r"70\s*W",
    "keyboard": r"中文\s*[（(]?\s*拼音\s*[）)]?|Chinese\s*\(?Pinyin\)?",
}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def history_previous() -> dict | None:
    if not HISTORY.exists():
        return None
    for line in reversed(HISTORY.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            item = json.loads(line)
            if item.get("verified") is True and item.get("url") == URL:
                return item
    return None


def safe_url(url: str) -> str:
    """Query parameters can contain session tokens; keep only the request path."""
    return url.split("?", 1)[0].split("#", 1)[0]


DOM_SCRIPT = r"""() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const label = e => {
    const parent = e.closest('label') || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.parentElement;
    return clean(parent?.innerText || e.getAttribute('aria-label') || e.value).slice(0, 500);
  };
  const choices = Array.from(document.querySelectorAll('input, [role="radio"], [role="option"], select, [aria-selected]'))
    .map(e => ({tag: e.tagName, role: e.getAttribute('role'), name: e.getAttribute('name'),
      label: label(e), value: e.value || null, checked: !!e.checked,
      ariaChecked: e.getAttribute('aria-checked'), ariaSelected: e.getAttribute('aria-selected'),
      selectedOption: e.tagName === 'SELECT' ? clean(e.selectedOptions[0]?.textContent) : null}))
    .filter(x => x.label || x.selectedOption);
  const summary = Array.from(document.querySelectorAll('[data-analytics-section="summary"], .rf-bfe-summary, [class*="purchaseinfo" i]'))
    .map(e => ({tag: e.tagName, selectorHint: e.id || e.className?.toString().slice(0, 180),
      text: clean(e.innerText).slice(0, 12000),
      priceNodes: Array.from(e.querySelectorAll('[class*="fullprice" i], [data-autom*="fullprice" i]'))
        .map(p => ({text: clean(p.innerText), html: p.outerHTML.slice(0, 1000),
          parentText: clean(p.parentElement?.innerText).slice(0, 200),
          parentHtml: p.parentElement?.outerHTML.slice(0, 1200)}))
        .filter(p => p.text)}))
    .filter(x => x.text && (/[¥￥]|RMB/.test(x.text)))
    .sort((a,b) => a.text.length - b.text.length).slice(0, 100);
  const prices = Array.from(document.querySelectorAll('body *'))
    .filter(e => e.children.length === 0 && /(?:[¥￥]\s*|RMB\s*)[\d,]+/.test(clean(e.textContent)))
    .slice(0, 100).map(e => ({text: clean(e.textContent),
      parent: clean(e.parentElement?.innerText).slice(0, 500),
      grandparent: clean(e.parentElement?.parentElement?.innerText).slice(0, 1200),
      html: e.outerHTML.slice(0, 1000)}));
  let serverSelections = null;
  try { serverSelections = JSON.parse(document.querySelector('#metrics')?.textContent || '{}')
    .data?.buyflow?.userSelections || null; } catch (_) {}
  if (!serverSelections) {
    try {
      const metrics = JSON.parse(document.querySelector('#metrics')?.textContent || '{}');
      serverSelections = metrics.buyflow?.userSelections || null;
    } catch (_) {}
  }
  return {title: document.title, url: location.href, bodyText: clean(document.body?.innerText).slice(0, 100000),
    choices, summary, prices, serverSelections};
}"""


def selected_text(dom: dict) -> str:
    selected = []
    for choice in dom["choices"]:
        if choice["checked"] or choice["ariaChecked"] == "true" or choice["ariaSelected"] == "true":
            selected.append(choice["label"])
        if choice["selectedOption"]:
            selected.append(choice["selectedOption"])
    return "\n".join(selected)


def select_keyboard(page) -> dict:
    """Act on an explicit Pinyin option, then verify its selected control state."""
    expression = re.compile(EXPECTED["keyboard"], re.I)
    before = page.evaluate(DOM_SCRIPT)
    selected = selected_text(before)
    initial = before.get("serverSelections") or {}
    if initial.get("KEYBOARD_LANGUAGE", {}).get("dimensionValue") == "chn":
        return {"selected": True, "action": "Apple page state already selects chn (Pinyin)",
                "selected_text": selected, "source": "#metrics buyflow.userSelections"}
    if expression.search(selected):
        return {"selected": True, "action": "already selected", "selected_text": selected}
    candidates = page.get_by_text(expression)
    count = min(candidates.count(), 15)
    errors = []
    for index in range(count):
        try:
            candidates.nth(index).click(timeout=3000)
            page.wait_for_timeout(1200)
            after = page.evaluate(DOM_SCRIPT)
            selected = selected_text(after)
            if expression.search(selected):
                return {"selected": True, "action": f"clicked text match {index}", "selected_text": selected}
        except Exception as exc:
            errors.append(f"match {index}: {exc}")
    return {"selected": False, "action": "no confirmed selection", "matches": count, "errors": errors}


def verify(dom: dict, keyboard: dict) -> tuple[dict, int | None, str | None]:
    selected = selected_text(dom)
    summaries = dom["summary"]
    selections = dom.get("serverSelections") or {}
    expected_state = {
        "SCREEN_SIZE": ("14inch", "SCREEN_SIZE"),
        "CHASSIS_COLOR": ("spaceblack", "CHASSIS_COLOR"),
        "DISPLAY_FINISH": ("standard", "DISPLAY_FINISH"),
        "MEMORY": ("24gb", "dimensionValue"),
        "STORAGE": ("1tb", "dimensionValue"),
        "POWER_ADAPTER": ("70w", "dimensionValue"),
        "KEYBOARD_LANGUAGE": ("chn", "dimensionValue"),
    }
    state_checks = {
        key: (selections.get(key, {}).get(field) if isinstance(selections.get(key), dict)
              else selections.get(key)) == expected
        for key, (expected, field) in expected_state.items()
    }
    processor = selections.get("PROCESSOR") or {}
    state_checks["PROCESSOR"] = (processor.get("dimensionChip") == "m5"
                                  and str(processor.get("cpuCoreCount")) == "10"
                                  and str(processor.get("gpuCoreCount")) == "10")
    state_checks["NO_PREINSTALLED_SOFTWARE"] = (
        selections.get("LOGIC_PRO", {}).get("dimensionValue") == "none"
        and selections.get("FINAL_CUT_PRO", {}).get("dimensionValue") == "none")
    # The site's selected product state verifies every configurable dimension.
    # Prices are read only from the rendered purchase-summary component.
    summary_field_checks = [
        {key: bool(re.search(pattern, block["text"], re.I)) for key, pattern in EXPECTED.items()}
        for block in summaries
    ]
    eligible = [block for block, fields in zip(summaries, summary_field_checks)
                if block.get("priceNodes") and all(fields.values())]
    checks = {
        "selected_keyboard": keyboard["selected"] and state_checks["KEYBOARD_LANGUAGE"],
        "apple_selected_state": state_checks,
        "all_selected_state": all(state_checks.values()),
        "purchase_summary_with_fullprice": bool(eligible),
        "summary_matches_configuration": any(all(fields.values()) for fields in summary_field_checks),
        "summary_field_checks": summary_field_checks,
        "keyboard_has_touch_id": bool(re.search(r"触控\s*ID|Touch\s*ID", selected, re.I))
        or bool(re.search(r"触控\s*ID|Touch\s*ID", dom.get("bodyText", ""), re.I)),
        "official_domain": dom["url"].startswith("https://www.apple.com.cn/shop/"),
    }
    if not all(value for key, value in checks.items() if key not in ("apple_selected_state", "summary_field_checks")):
        return checks, None, "configuration or purchase summary could not be confirmed"
    # Apple's full-price component is the one-time purchase price. Reject
    # comparative "starting at" amounts and require one value in the summary.
    total_candidates = []
    for block in eligible:
        for node in block.get("priceNodes", []):
            if "起" in node["text"] or "起" in node.get("parentText", ""):
                continue
            if "comparative" in (node.get("html", "") + node.get("parentHtml", "")).lower():
                continue
            if re.search(r"分期|每月|每期|教育|翻新|折抵|换购|AppleCare", node["text"], re.I):
                continue
            values = PRICE_RE.findall(node["text"])
            if len(values) == 1:
                total_candidates.append(int(values[0].replace(",", "")))
    unique = sorted(set(total_candidates))
    checks["unique_one_time_total"] = len(unique) == 1
    if len(unique) != 1:
        return checks, None, f"one-time total ambiguous: {unique}"
    return checks, unique[0], None


def main() -> int:
    now = datetime.now(SHANGHAI)
    out = ROOT / "evidence" / now.strftime("%Y%m%dT%H%M%S%z")
    out.mkdir(parents=True, exist_ok=True)
    result = {"queried_at": now.isoformat(), "url": URL, "verified": False,
              "currency": "CNY", "price_cny": None, "browser_started": False,
              "screenshot": None, "keyboard": None, "checks": {}, "error": None}
    errors: list[str] = []
    page = None
    browser = None
    network = (out / "network.jsonl").open("w", encoding="utf-8")

    def log_network(entry: dict) -> None:
        network.write(json.dumps(entry, ensure_ascii=False) + "\n")
        network.flush()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = os.environ.get("CHROMIUM_EXECUTABLE")
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            result["browser_started"] = True
            result["browser_executable_override"] = executable
            context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai",
                                          viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on("request", lambda request: log_network({"event": "request", "method": request.method,
                                                              "url": safe_url(request.url)}))
            page.on("response", lambda response: log_network({"event": "response", "status": response.status,
                                                                "url": safe_url(response.url),
                                                                "content_type": response.headers.get("content-type", "")}))
            page.on("requestfailed", lambda request: log_network({"event": "requestfailed", "url": safe_url(request.url),
                                                                     "failure": request.failure}))
            page.on("console", lambda message: errors.append(f"console {message.type}: {message.text}"))
            page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
            response = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            result["navigation_status"] = response.status if response else None
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception as exc:
                errors.append(f"networkidle: {exc}")
            page.wait_for_timeout(3000)
            result["keyboard"] = select_keyboard(page)
            page.wait_for_timeout(2000)
            dom = page.evaluate(DOM_SCRIPT)
            write_json(out / "dom.json", dom)
            (out / "configuration_summary.txt").write_text(
                "Selected controls:\n" + selected_text(dom) + "\n\nPurchase summary candidates:\n" +
                "\n\n".join(item["text"] for item in dom["summary"]) + "\n", encoding="utf-8"
            )
            (out / "page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(out / "page.png"), full_page=True, timeout=30000)
            result["screenshot"] = "page.png"
            result["final_url"] = page.url
            checks, price, failure = verify(dom, result["keyboard"])
            result["checks"] = checks
            result["selected_configuration"] = selected_text(dom)
            result["purchase_summaries"] = dom["summary"]
            if failure:
                result["error"] = failure
            else:
                result["price_cny"] = price
                result["verified"] = True
            browser.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        errors.append(traceback.format_exc())
        if page is not None:
            try:
                (out / "page.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(out / "page.png"), full_page=True, timeout=10000)
                result["screenshot"] = "page.png"
                write_json(out / "dom.json", page.evaluate(DOM_SCRIPT))
            except Exception as capture_exc:
                errors.append(f"evidence capture: {capture_exc}")
    finally:
        network.close()
        (out / "errors.log").write_text("\n".join(errors) + "\n", encoding="utf-8")

    previous = history_previous()
    result["previous_verified_price_cny"] = previous.get("price_cny") if previous else None
    result["price_change_cny"] = (result["price_cny"] - previous["price_cny"]
                                  if result["verified"] and previous else None)
    write_json(out / "result.json", result)
    if result["verified"]:
        record = {"queried_at": result["queried_at"], "url": URL, "verified": True,
                  "currency": "CNY", "price_cny": result["price_cny"],
                  "previous_verified_price_cny": result["previous_verified_price_cny"],
                  "price_change_cny": result["price_change_cny"]}
        with HISTORY.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"verified": result["verified"], "price_cny": result["price_cny"],
                      "error": result["error"], "evidence": str(out)}, ensure_ascii=False))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
