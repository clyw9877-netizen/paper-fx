"""
Бумажный FX на реальных котировках Yahoo.
EURUSD=X, GBPUSD=X, USDJPY=X, AUDCHF=X. Без ключа.
Ордеров на брокер нет. Депозит $500, риск $10, тейк 2R, комиссия $0.70 на сторону.
Если Yahoo молчит — второй хост, потом страница пишет, что лента старая.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = 500.0
RISK = 10.0
COMMISSION = 0.70
SYMBOLS = ("EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDCHF=X")

equity = START
positions: dict[str, dict] = {}
closed: list[dict] = []
prices: dict[str, float] = {}
source = "нет данных"
lock = threading.Lock()


def fetch_one(symbol: str, host: str) -> float:
    url = f"https://{host}/v8/finance/chart/{symbol}?range=1d&interval=1m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    last = next(x for x in reversed(closes) if x is not None)
    return float(last)


def refresh_prices() -> None:
    global source
    got: dict[str, float] = {}
    used = ""
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            for s in SYMBOLS:
                got[s] = fetch_one(s, host)
            used = f"Yahoo {host} 1m"
            break
        except Exception:
            got = {}
    with lock:
        if got:
            prices.update(got)
            source = used
        else:
            source = "Yahoo недоступен, цены старые"


def maybe_open() -> None:
    global equity
    if len(positions) >= 2 or not prices:
        return
    for s, px in prices.items():
        if s in positions:
            continue
        side = "long" if int(px * 10000) % 2 == 0 else "short"
        risk = px * 0.0015
        stop = px - risk if side == "long" else px + risk
        take = px + risk * 2 if side == "long" else px - risk * 2
        equity -= COMMISSION
        positions[s] = {"s": s, "side": side, "entry": px, "stop": stop, "take": take, "u": 0.0}
        return


def mark() -> None:
    global equity
    done = []
    for s, p in positions.items():
        px = prices.get(s)
        if px is None:
            continue
        direction = 1 if p["side"] == "long" else -1
        p["u"] = (px - p["entry"]) / abs(p["entry"] - p["stop"]) * RISK * direction
        hit_stop = px <= p["stop"] if p["side"] == "long" else px >= p["stop"]
        hit_take = px >= p["take"] if p["side"] == "long" else px <= p["take"]
        if hit_stop or hit_take:
            pnl = (RISK * 2 if hit_take else -RISK) - COMMISSION
            equity += pnl
            closed.insert(0, {"s": s, "side": p["side"], "pnl": round(pnl, 2), "why": "тейк" if hit_take else "стоп"})
            del closed[30:]
            done.append(s)
    for s in done:
        del positions[s]
    if not positions:
        maybe_open()


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
            "note": "real yahoo quotes, paper orders only",
        }


def loop() -> None:
    while True:
        refresh_prices()
        with lock:
            mark()
        time.sleep(30)


PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Paper FX real</title>
<style>
body{margin:0;font-family:-apple-system,sans-serif;background:#101010;color:#f3f3f3}
main{max-width:760px;margin:0 auto;padding:18px 14px 40px}
.muted{color:#9a9a9a}.up{color:#3dd68c}.down{color:#ff5d5d}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.card{background:#1b1b1b;border-radius:14px;padding:12px;margin:8px 0}
.row{display:flex;justify-content:space-between;margin-top:4px;color:#ccc}
</style></head><body><main>
<h1>Paper FX</h1>
<p class="muted">Цены Yahoo по EURUSD, GBPUSD, USDJPY, AUDCHF. Ордера бумажные, брокер не подключён.</p>
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
    `<div class="card"><div class="row"><b class="${x.side=='long'?'up':'down'}">${x.s} ${x.side}</b><b class="${x.u>=0?'up':'down'}">${x.u.toFixed(2)}</b></div>
     <div class="row"><span>вход</span><span>${x.entry.toFixed(5)}</span></div>
     <div class="row"><span>стоп</span><span>${x.stop.toFixed(5)}</span></div>
     <div class="row"><span>тейк 2R</span><span>${x.take.toFixed(5)}</span></div></div>`).join('') || '<div class="card">ждёт цену</div>';
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
