"""
Бумажный Alex G по разбору Мусы. Не заглушка.
Цены Yahoo, без ключа. Ордеров нет. Депозит $500, риск $200, комиссия $1.40.

Два сетапа:
1) Контртренд у сопротивления/поддержки старшего графика:
   история слева, доджи или поглощение у зоны, слом локальной структуры,
   стоп за экстремум, тейк у противоположной зоны, не в пустоте.
2) По тренду только у зоны и только по закрытой свече.
Нет зоны или нет подтверждения — сделки нет.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = 500.0
RISK = 200.0
COMMISSION = 1.40
SYMBOLS = (
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "USDCHF=X",
    "AUDUSD=X",
    "NZDUSD=X",
    "USDCAD=X",
    "EURGBP=X",
    "GBPNZD=X",
    "AUDJPY=X",
    "GBPJPY=X",
    "CADJPY=X",
    "GC=F",
)

equity = START
positions: dict[str, dict] = {}
closed: list[dict] = []
prices: dict[str, float] = {}
source = "нет данных"
lock = threading.Lock()


def fetch(symbol: str, host: str, interval: str, range_: str) -> list[dict]:
    url = f"https://{host}/v8/finance/chart/{symbol}?range={range_}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    q = data["chart"]["result"][0]["indicators"]["quote"][0]
    out = []
    for o, h, l, c in zip(q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        out.append({"o": o, "h": h, "l": l, "c": c})
    return out


def bearish_engulf(prev: dict, cur: dict) -> bool:
    return cur["c"] < cur["o"] and prev["c"] > prev["o"] and cur["o"] >= prev["c"] and cur["c"] <= prev["o"]


def bullish_engulf(prev: dict, cur: dict) -> bool:
    return cur["c"] > cur["o"] and prev["c"] < prev["o"] and cur["o"] <= prev["c"] and cur["c"] >= prev["o"]


def doji(c: dict) -> bool:
    rng = c["h"] - c["l"]
    return rng > 0 and abs(c["c"] - c["o"]) / rng < 0.25


def zone(candles: list[dict], side: str) -> float | None:
    if len(candles) < 20:
        return None
    sample = candles[-40:-2]
    anchor = max(c["h"] for c in sample) if side == "short" else min(c["l"] for c in sample)
    band = anchor * 0.002
    hits = [c for c in sample if abs((c["h"] if side == "short" else c["l"]) - anchor) <= band]
    if len(hits) < 2:
        return None
    left = sample[: len(sample) // 2]
    if side == "short" and max(c["h"] for c in left) < anchor * 0.998:
        return None
    if side == "long" and min(c["l"] for c in left) > anchor * 1.002:
        return None
    return anchor


def setup(daily: list[dict], h4: list[dict]) -> dict | None:
    if len(daily) < 25 or len(h4) < 20:
        return None
    d1, d2 = daily[-2], daily[-1]
    p, c = h4[-2], h4[-1]
    res = zone(daily, "short")
    sup = zone(daily, "long")
    band = d2["c"] * 0.0025
    trend_up = daily[-1]["c"] > daily[-10]["c"]

    if res and d2["h"] >= res - band and (doji(d2) or bearish_engulf(d1, d2)):
        higher_low = min(x["l"] for x in h4[-8:-2])
        if d2["c"] < higher_low and c["h"] < h4[-3]["h"] and (bearish_engulf(p, c) or doji(c)):
            entry = c["c"]
            stop = max(c["h"], d2["h"])
            risk = stop - entry
            demand = sup if sup and sup < entry - risk else None
            if risk <= 0 or demand is None:
                return None
            return {"side": "short", "entry": entry, "stop": stop, "take": demand, "why": "контртренд у сопротивления"}

    if sup and d2["l"] <= sup + band and (doji(d2) or bullish_engulf(d1, d2)):
        lower_high = max(x["h"] for x in h4[-8:-2])
        if d2["c"] > lower_high and c["l"] > h4[-3]["l"] and (bullish_engulf(p, c) or doji(c)):
            entry = c["c"]
            stop = min(c["l"], d2["l"])
            risk = entry - stop
            supply = res if res and res > entry + risk else None
            if risk <= 0 or supply is None:
                return None
            return {"side": "long", "entry": entry, "stop": stop, "take": supply, "why": "контртренд у поддержки"}

    if trend_up and sup and c["l"] <= sup + band and bullish_engulf(p, c):
        entry, stop = c["c"], min(c["l"], sup)
        risk = entry - stop
        if risk <= 0 or not res or res < entry + risk * 2:
            return None
        return {"side": "long", "entry": entry, "stop": stop, "take": res, "why": "по тренду у зоны"}
    if not trend_up and res and c["h"] >= res - band and bearish_engulf(p, c):
        entry, stop = c["c"], max(c["h"], res)
        risk = stop - entry
        if risk <= 0 or not sup or sup > entry - risk * 2:
            return None
        return {"side": "short", "entry": entry, "stop": stop, "take": sup, "why": "по тренду у зоны"}
    return None


def refresh() -> None:
    global source, equity
    packs = {}
    used = ""
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            for s in SYMBOLS:
                packs[s] = {
                    "d": fetch(s, host, "1d", "1y"),
                    "h": fetch(s, host, "1h", "3mo"),
                }
            used = "Yahoo daily+1h, вход только у зоны"
            break
        except Exception:
            packs = {}
    with lock:
        source = used or "Yahoo недоступен"
        if not packs:
            return
        for s, pack in packs.items():
            prices[s] = pack["h"][-1]["c"]
            if s in positions:
                p = positions[s]
                px = prices[s]
                direction = 1 if p["side"] == "long" else -1
                p["u"] = (px - p["entry"]) / abs(p["entry"] - p["stop"]) * RISK * direction
                hit_stop = px <= p["stop"] if p["side"] == "long" else px >= p["stop"]
                hit_take = px >= p["take"] if p["side"] == "long" else px <= p["take"]
                if hit_stop or hit_take:
                    dist = abs(p["entry"] - p["stop"])
                    rr = abs(p["take"] - p["entry"]) / dist if dist else 1
                    pnl = (RISK * rr if hit_take else -RISK) - COMMISSION
                    equity += pnl
                    closed.insert(0, {"s": s, "side": p["side"], "pnl": round(pnl, 2), "why": p["why"]})
                    del closed[20:]
                    del positions[s]
            if s not in positions and len(positions) < 2:
                sig = setup(pack["d"], pack["h"])
                if sig:
                    equity -= COMMISSION
                    sig.update({"s": s, "u": 0.0})
                    positions[s] = sig


def snapshot() -> dict:
    with lock:
        unreal = sum(p["u"] for p in positions.values())
        return {
            "equity": round(equity + unreal, 2),
            "pnl": round(equity + unreal - START, 2),
            "source": source,
            "prices": prices,
            "open": list(positions.values()),
            "closed": closed[:12],
            "note": "Musa Alex logic, paper only",
        }


def loop() -> None:
    while True:
        refresh()
        time.sleep(60)


PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Alex paper</title>
<style>
body{margin:0;font-family:-apple-system,sans-serif;background:#101010;color:#f3f3f3}
main{max-width:760px;margin:0 auto;padding:18px 14px 40px}
.muted{color:#9a9a9a}.up{color:#3dd68c}.down{color:#ff5d5d}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.card{background:#1b1b1b;border-radius:14px;padding:12px;margin:8px 0}
.row{display:flex;justify-content:space-between;margin-top:4px;color:#ccc}
</style></head><body><main>
<h1>Alex G paper</h1>
<p class="muted">Зона на дневке, подтверждение свечой, тейк у противоположной зоны. Нет зоны — входа нет. Риск $200. Не брокер.</p>
<div class="grid">
<div class="card">депозит<b id="eq">—</b></div>
<div class="card">pnl<b id="pnl">—</b></div>
<div class="card">открыто<b id="n">—</b></div>
</div>
<p class="muted" id="src"></p>
<h2>Висит</h2><div id="live"></div>
<h2>Закрытые</h2><div id="hist"></div>
<script>
async function refresh(){
  const s = await (await fetch('/api/state')).json();
  document.getElementById('eq').textContent = s.equity.toFixed(2);
  const p = document.getElementById('pnl');
  p.textContent = (s.pnl>=0?'+':'') + s.pnl.toFixed(2);
  p.className = s.pnl>=0?'up':'down';
  document.getElementById('n').textContent = s.open.length;
  document.getElementById('src').textContent = s.source;
  document.getElementById('live').innerHTML = s.open.map(x =>
    `<div class="card"><div class="row"><b class="${x.side=='long'?'up':'down'}">${x.s} ${x.side}</b><b>${x.u.toFixed(2)}</b></div>
     <div class="row"><span>${x.why}</span><span></span></div>
     <div class="row"><span>вход</span><span>${x.entry.toFixed(5)}</span></div>
     <div class="row"><span>стоп</span><span>${x.stop.toFixed(5)}</span></div>
     <div class="row"><span>тейк у зоны</span><span>${x.take.toFixed(5)}</span></div></div>`).join('') || '<div class="card">скип, нет зоны или свечи</div>';
  document.getElementById('hist').innerHTML = s.closed.map(x =>
    `<div class="card"><div class="row"><span>${x.s} ${x.side} ${x.why}</span><b class="${x.pnl>=0?'up':'down'}">${x.pnl.toFixed(2)}</b></div></div>`).join('');
}
refresh(); setInterval(refresh, 5000);
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/state"):
            body = json.dumps(snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
