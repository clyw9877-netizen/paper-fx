"""
Бумажный FX-сервер для Railway.
Крутится сам, пока жив процесс. Страница только читает /api/state.
Депозит $500. Не брокер. Ордеров нет.
Логика урезана до кода: не больше 2 позиций, риск $10, тейк 2R, стоп 1R.
"""

from __future__ import annotations

import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = 500.0
RISK = 10.0
PAIRS = [
    {"s": "EURUSD", "p": 1.0850},
    {"s": "GBPUSD", "p": 1.3120},
    {"s": "USDJPY", "p": 149.20},
    {"s": "AUDCHF", "p": 0.5650},
]

equity = START
positions: list[dict] = []
closed: list[dict] = []
lock = threading.Lock()
rng = random.Random()


def tick() -> None:
    global equity
    with lock:
        for x in PAIRS:
            x["p"] *= 1 + (rng.random() - 0.48) * 0.0012
        still = []
        for p in positions:
            px = next(x["p"] for x in PAIRS if x["s"] == p["s"])
            direction = 1 if p["side"] == "long" else -1
            p["u"] = (px - p["entry"]) / abs(p["entry"] - p["stop"]) * RISK * direction
            hit_stop = px <= p["stop"] if p["side"] == "long" else px >= p["stop"]
            hit_take = px >= p["take"] if p["side"] == "long" else px <= p["take"]
            if hit_stop or hit_take:
                pnl = RISK * 2 if hit_take else -RISK
                equity += pnl
                closed.insert(0, {"s": p["s"], "side": p["side"], "pnl": pnl, "why": "тейк" if hit_take else "стоп"})
                del closed[30:]
            else:
                still.append(p)
        positions[:] = still
        if len(positions) < 2 and rng.random() < 0.25:
            x = rng.choice(PAIRS)
            if any(p["s"] == x["s"] for p in positions):
                return
            side = "long" if rng.random() > 0.5 else "short"
            entry = x["p"]
            risk = entry * 0.0025
            stop = entry - risk if side == "long" else entry + risk
            take = entry + risk * 2 if side == "long" else entry - risk * 2
            positions.append({"s": x["s"], "side": side, "entry": entry, "stop": stop, "take": take, "u": 0.0})


def snapshot() -> dict:
    with lock:
        unreal = sum(p["u"] for p in positions)
        return {
            "equity": round(equity + unreal, 2),
            "pnl": round(equity + unreal - START, 2),
            "start": START,
            "open": positions,
            "closed": closed[:12],
            "note": "paper only, fake prices, no broker",
        }


def loop() -> None:
    while True:
        tick()
        time.sleep(2)


PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Paper FX</title>
<style>
body{margin:0;font-family:-apple-system,sans-serif;background:#101010;color:#f3f3f3}
main{max-width:760px;margin:0 auto;padding:18px 14px 40px}
.muted{color:#9a9a9a}.up{color:#3dd68c}.down{color:#ff5d5d}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.card{background:#1b1b1b;border-radius:14px;padding:12px;margin:8px 0}
.row{display:flex;justify-content:space-between;margin-top:4px;color:#ccc}
</style></head><body><main>
<h1>Paper FX</h1>
<p class="muted">Сервер крутит бумагу сам. Депозит $500. Это не брокер.</p>
<div class="grid">
<div class="card">депозит<b id="eq">—</b></div>
<div class="card">pnl<b id="pnl">—</b></div>
<div class="card">открыто<b id="n">—</b></div>
</div>
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
  document.getElementById('live').innerHTML = s.open.map(x =>
    `<div class="card"><div class="row"><b class="${x.side=='long'?'up':'down'}">${x.s} ${x.side}</b><b class="${x.u>=0?'up':'down'}">${x.u.toFixed(2)}</b></div>
     <div class="row"><span>вход</span><span>${x.entry.toFixed(4)}</span></div>
     <div class="row"><span>стоп</span><span>${x.stop.toFixed(4)}</span></div>
     <div class="row"><span>тейк</span><span>${x.take.toFixed(4)}</span></div></div>`).join('') || '<div class="card">пусто</div>';
  document.getElementById('hist').innerHTML = s.closed.map(x =>
    `<div class="card"><div class="row"><span>${x.s} ${x.side} ${x.why}</span><b class="${x.pnl>=0?'up':'down'}">${x.pnl.toFixed(2)}</b></div></div>`).join('');
}
refresh(); setInterval(refresh, 2000);
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
    import os
    port = int(os.environ.get("PORT", "8080"))
    threading.Thread(target=loop, daemon=True).start()
    print(f"paper fx on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
