"""
GitHub Actions 用データ更新スクリプト。
symbols.json に列挙された銘柄の Yahoo!ファイナンス データを取得し、
data/quotes.json と data/charts/*.json に保存する。
"""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0"}
SYMBOLS_FILE = "symbols.json"
DATA_DIR = "data"
CHART_DIR = os.path.join(DATA_DIR, "charts")


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as res:
        return json.loads(res.read().decode())


def safe_name(sym: str) -> str:
    """ファイル名として安全なシンボル表記。フロントエンドと共通のルール。"""
    return re.sub(r"[^A-Za-z0-9.^=-]", "_", sym)


def series(sym: str, rng: str, interval: str, intraday: bool):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(sym)}?range={rng}&interval={interval}"
    )
    try:
        chart = fetch_json(url).get("chart") or {}
    except Exception as e:
        print(f"  ! {sym} {rng}: {e}")
        return []
    results = chart.get("result") or []
    if not results:
        return []
    r0 = results[0]
    ts = r0.get("timestamp") or []
    ind = r0.get("indicators") or {}
    closes = ((ind.get("quote") or [{}])[0].get("close")) or []
    pts = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        dt = datetime.fromtimestamp(t, JST)
        fmt = "%H:%M" if intraday else "%m/%d"
        pts.append([dt.strftime(fmt), round(float(c), 2)])
    return pts


def main():
    os.makedirs(CHART_DIR, exist_ok=True)
    with open(SYMBOLS_FILE, encoding="utf-8") as f:
        symbols = json.load(f)

    quotes = []
    keep = set()
    for entry in symbols:
        sym = entry["symbol"]
        name = entry.get("name", "")
        print(f"- {sym} ({name})")

        p1m = series(sym, "1d", "1m", intraday=True)
        p5m = series(sym, "1d", "5m", intraday=True)
        pd_ = series(sym, "1mo", "1d", intraday=False)

        # 最新価格は 1分足の meta から取得
        meta = {}
        try:
            url = (
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{urllib.parse.quote(sym)}?range=1d&interval=1m"
            )
            meta = (fetch_json(url).get("chart", {}).get("result") or [{}])[0].get("meta", {})
        except Exception as e:
            print(f"  ! {sym} meta: {e}")

        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        q = {
            "symbol": sym,
            "name": name or meta.get("shortName", ""),
            "currency": meta.get("currency", ""),
            "price": price,
            "previous_close": prev,
            "time": meta.get("regularMarketTime"),
        }
        if price is not None and prev:
            q["change"] = round(price - prev, 2)
            q["change_percent"] = round((price - prev) / prev * 100, 2)
        quotes.append(q)
        keep.add(safe_name(sym))

        chart_data = {}
        if p1m:
            chart_data["1m"] = p1m
        if p5m:
            chart_data["5m"] = p5m
        if pd_:
            chart_data["d"] = pd_
        if chart_data:
            path = os.path.join(CHART_DIR, f"{safe_name(sym)}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(chart_data, f, ensure_ascii=False, separators=(",", ":"))

    # 取得対象から外れた銘柄の古いチャートファイルを削除
    for fn in os.listdir(CHART_DIR):
        if fn.endswith(".json") and fn[:-5] not in keep:
            os.remove(os.path.join(CHART_DIR, fn))
            print(f"  x removed stale chart: {fn}")

    payload = {
        "updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        "quotes": quotes,
    }
    with open(os.path.join(DATA_DIR, "quotes.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"done: {len(quotes)} symbols")


if __name__ == "__main__":
    main()
