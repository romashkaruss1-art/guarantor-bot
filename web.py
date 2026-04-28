"""FastAPI web — кабинет пользователя + админка. Бизнес-логика только в core.py."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

import core
import db


def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "admin")


def _bot_username() -> str:
    return core.BOT_USERNAME or os.environ.get("BOT_USERNAME", "")


app = FastAPI(title="Guarantor — P2P Escrow")


# ---------- HTML helpers ----------

BRAND = "Guarantor"
TAGLINE = "Безопасные P2P-сделки с гарантом"

BASE_CSS = """
<style>
  :root {
    --bg: #0a0d12;
    --bg-2: #0f141b;
    --panel: #131923;
    --panel-2: #18202c;
    --border: #232c3a;
    --text: #e7ecf3;
    --muted: #8a96a8;
    --accent: #38d39f;
    --accent-2: #2cc7ff;
    --warn: #ffb547;
    --danger: #ff6b6b;
    --shadow: 0 10px 30px rgba(0,0,0,.35);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif;
    background:
      radial-gradient(1100px 600px at 80% -10%, rgba(56,211,159,.12), transparent 60%),
      radial-gradient(900px 500px at -10% 10%, rgba(44,199,255,.10), transparent 60%),
      var(--bg);
    color: var(--text);
    line-height: 1.55;
    min-height: 100vh;
  }
  a { color: var(--accent-2); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .topbar {
    position: sticky; top: 0; z-index: 10;
    background: rgba(10,13,18,.85);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
  }
  .topbar-inner {
    max-width: 1100px; margin: 0 auto; padding: 14px 24px;
    display: flex; align-items: center; gap: 22px;
  }
  .brand {
    display: flex; align-items: center; gap: 10px;
    font-weight: 700; font-size: 18px; color: #fff;
  }
  .brand-logo {
    width: 32px; height: 32px; border-radius: 9px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    display: grid; place-items: center;
    box-shadow: 0 6px 18px rgba(56,211,159,.35);
  }
  .nav { margin-left: auto; display: flex; gap: 18px; align-items: center; }
  .nav a { color: var(--muted); font-weight: 500; font-size: 14px; }
  .nav a:hover { color: #fff; text-decoration: none; }
  .nav .pill {
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #062018; padding: 8px 14px; border-radius: 999px; font-weight: 700;
  }
  .nav .pill:hover { color: #062018; }

  main { max-width: 1100px; margin: 0 auto; padding: 28px 24px 64px; }

  h1, h2, h3, h4 { color: #fff; margin: 0 0 12px; letter-spacing: -0.01em; }
  h1 { font-size: 36px; font-weight: 800; }
  h2 { font-size: 22px; font-weight: 700; margin-top: 8px; }
  h3 { font-size: 16px; font-weight: 700; }
  p  { color: #c5cfdc; }
  .muted { color: var(--muted); font-size: 13px; }

  .hero {
    display: grid; grid-template-columns: 1.2fr .8fr; gap: 28px; align-items: stretch;
    margin-bottom: 28px;
  }
  @media (max-width: 880px) { .hero { grid-template-columns: 1fr; } }
  .hero-card {
    background: linear-gradient(180deg, var(--panel), var(--bg-2));
    border: 1px solid var(--border); border-radius: 16px; padding: 28px;
    box-shadow: var(--shadow);
  }
  .hero h1 { font-size: 38px; line-height: 1.1; }
  .hero .lead { font-size: 16px; color: #c5cfdc; max-width: 520px; }
  .badges { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
  .chip {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(56,211,159,.10); color: #b8f0d6;
    border: 1px solid rgba(56,211,159,.25);
    padding: 6px 12px; border-radius: 999px; font-size: 12px; font-weight: 600;
  }
  .chip svg { width: 14px; height: 14px; }
  .chip.alt { background: rgba(44,199,255,.10); color: #b6e6ff; border-color: rgba(44,199,255,.25); }
  .chip.warn { background: rgba(255,181,71,.10); color: #ffd58a; border-color: rgba(255,181,71,.25); }

  .cta-row { display: flex; gap: 12px; margin-top: 22px; flex-wrap: wrap; }
  .btn {
    display: inline-flex; align-items: center; gap: 8px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #062018; font-weight: 700;
    border: 0; padding: 11px 18px; border-radius: 10px; cursor: pointer; font-size: 14px;
    box-shadow: 0 6px 18px rgba(56,211,159,.25);
  }
  .btn:hover { transform: translateY(-1px); text-decoration: none; color: #062018; }
  .btn.ghost {
    background: transparent; color: var(--text); border: 1px solid var(--border);
    box-shadow: none;
  }
  .btn.ghost:hover { border-color: var(--accent); color: #fff; }
  .btn.danger {
    background: linear-gradient(135deg, #ff6b6b, #c93838); color: #fff; box-shadow: none;
  }
  .btn.small { padding: 7px 12px; font-size: 13px; }
  .btn svg { width: 16px; height: 16px; }

  .stats {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 22px;
  }
  @media (max-width: 720px) { .stats { grid-template-columns: repeat(2, 1fr); } }
  .stat {
    background: var(--panel-2); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px;
  }
  .stat .num { font-size: 22px; font-weight: 800; color: #fff; }
  .stat .lbl { font-size: 12px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: .04em; }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 720px) { .grid-2 { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 20px; margin-bottom: 16px; box-shadow: var(--shadow);
  }
  .card h3 { margin-top: 0; }

  .steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  @media (max-width: 880px) { .steps { grid-template-columns: repeat(2, 1fr); } }
  .step {
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 16px;
  }
  .step .n {
    display: inline-grid; place-items: center; width: 28px; height: 28px;
    border-radius: 8px; background: rgba(56,211,159,.12); color: var(--accent);
    font-weight: 800; font-size: 13px; margin-bottom: 8px;
  }
  .step h4 { font-size: 15px; margin: 4px 0 4px; }
  .step p { margin: 0; color: var(--muted); font-size: 13px; }

  .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  @media (max-width: 880px) { .features { grid-template-columns: 1fr; } }
  .feat {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px; box-shadow: var(--shadow);
  }
  .feat .icon {
    width: 38px; height: 38px; border-radius: 10px;
    display: grid; place-items: center; margin-bottom: 10px;
    background: rgba(56,211,159,.10); color: var(--accent);
  }
  .feat .icon.alt { background: rgba(44,199,255,.10); color: var(--accent-2); }
  .feat .icon.warn { background: rgba(255,181,71,.10); color: var(--warn); }
  .feat h4 { font-size: 15px; margin: 0 0 6px; }
  .feat p { color: var(--muted); margin: 0; font-size: 13px; }

  table { width: 100%; border-collapse: separate; border-spacing: 0; }
  th, td { padding: 12px 14px; text-align: left; font-size: 14px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; background: var(--panel-2); }
  tr:last-child td { border-bottom: 0; }

  .badge {
    display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
    background: var(--border); color: #cfd8e3;
  }
  .badge.created { background:#22344a; color:#9ec5ff; }
  .badge.waiting_payment { background:#3d3826; color:#ffd58a; }
  .badge.paid { background:#1d3a2c; color:#9affc5; }
  .badge.payment_confirmed { background:#1d2e3a; color:#9ad8ff; }
  .badge.goods_sent { background:#2a2740; color:#cab8ff; }
  .badge.dispute { background:#3d2024; color:#ff9e9e; }
  .badge.completed { background:#1d3a3a; color:#9aeaff; }
  .badge.cancelled { background:#262b34; color:#9aa4b2; }

  form { display: inline; }
  input[type=text], input[type=number], input[type=password], textarea, select {
    background: var(--bg-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 12px; width: 100%; max-width: 360px;
    font-family: inherit; font-size: 14px;
  }
  input:focus, textarea:focus, select:focus { outline: 2px solid var(--accent); border-color: transparent; }
  label { display: block; margin: 10px 0 6px; color: var(--muted); font-size: 13px; }

  .actions form { margin-right: 6px; margin-bottom: 6px; }
  .actions input[type=text] { max-width: 180px; }

  .deal-meta { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 24px; }
  @media (max-width: 600px) { .deal-meta { grid-template-columns: 1fr; } }
  .deal-meta div { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px dashed var(--border); }
  .deal-meta div b { color: #fff; }

  footer {
    border-top: 1px solid var(--border); margin-top: 40px; padding: 24px;
    text-align: center; color: var(--muted); font-size: 13px;
  }
  footer .marks { display: inline-flex; gap: 14px; margin-top: 8px; }
  footer .mark { display: inline-flex; align-items: center; gap: 6px; }
  footer svg { width: 14px; height: 14px; }

  .copybox {
    display: flex; gap: 8px; align-items: stretch;
    background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px; color: #cfe5ff; word-break: break-all;
  }
</style>
"""

ICONS = {
    "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z"/></svg>',
    "lock":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
    "check":  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M4 12l5 5 11-12"/></svg>',
    "scale":  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0L5 7zm14 0l-3 7a4 4 0 0 0 6 0l-3-7z"/></svg>',
    "bolt":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></svg>',
    "user":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6"/></svg>',
    "tg":     '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M9.5 16.5l-.4 4.1c.6 0 .8-.2 1.1-.5l2.6-2.5 5.4 4c1 .5 1.7.3 2-.9l3.5-16.4c.3-1.4-.5-2-1.5-1.6L1.6 10.4c-1.4.5-1.4 1.4-.2 1.7l5.4 1.7L19.4 5.5c.6-.3 1.1-.1.7.3"/></svg>',
    "doc":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/><path d="M14 2v6h6"/></svg>',
    "key":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="8" cy="15" r="4"/><path d="M11 12l8-8 3 3-3 3-2-2-2 2-2-2-2 2"/></svg>',
}


def page(title: str, body: str, *, hide_chrome: bool = False) -> str:
    nav = "" if hide_chrome else f"""
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="/" style="text-decoration:none">
          <span class="brand-logo">{ICONS['shield']}</span>
          <span>{BRAND}</span>
        </a>
        <nav class="nav">
          <a href="/">Главная</a>
          <a href="/#how">Как работает</a>
          <a href="/admin">Админка</a>
          {'<a class="pill" href="https://t.me/' + _bot_username() + '">Открыть бота</a>' if _bot_username() else ''}
        </nav>
      </div>
    </header>
    """
    footer = """
    <footer>
      <div>© {brand}. Сделки защищены escrow-механикой.</div>
      <div class="marks">
        <span class="mark">{lock} TLS-шифрование</span>
        <span class="mark">{shield} Средства в эскроу</span>
        <span class="mark">{scale} Арбитраж по спорам</span>
      </div>
    </footer>
    """.format(brand=BRAND, lock=ICONS['lock'], shield=ICONS['shield'], scale=ICONS['scale'])

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} — {BRAND}</title>
  <meta name="description" content="{TAGLINE} с гарантом сделки и арбитражем." />
  {BASE_CSS}
</head>
<body>
  {nav}
  <main>{body}</main>
  {footer}
</body>
</html>"""


def status_badge(status: str) -> str:
    label = {
        "created": "создана",
        "waiting_payment": "ожидает оплаты",
        "paid": "оплачено покупателем",
        "payment_confirmed": "оплата подтверждена",
        "goods_sent": "товар отправлен",
        "dispute": "спор",
        "completed": "завершена",
        "cancelled": "отменена",
    }.get(status, status)
    return f"<span class='badge {status}'>{label}</span>"


def _stats() -> dict:
    deals = core.list_all_deals()
    users = core.list_all_users()
    completed = [d for d in deals if d["status"] == "completed"]
    volume = sum(float(d["amount"]) for d in completed)
    in_escrow = [d for d in deals if d["status"] in ("waiting_payment", "paid", "dispute")]
    return {
        "deals_total": len(deals),
        "deals_completed": len(completed),
        "users": len(users),
        "volume": volume,
        "in_escrow": len(in_escrow),
    }


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
async def index():
    s = _stats()
    bot = _bot_username()
    bot_btn = (
        f"<a class='btn' href='https://t.me/{bot}' target='_blank'>{ICONS['tg']} Открыть бота в Telegram</a>"
        if bot else
        "<span class='chip warn'>Бот не подключён</span>"
    )
    body = f"""
    <section class="hero">
      <div class="hero-card">
        <div class="badges">
          <span class="chip">{ICONS['shield']} Escrow-защита</span>
          <span class="chip alt">{ICONS['scale']} Арбитраж</span>
          <span class="chip">{ICONS['lock']} TLS-шифрование</span>
        </div>
        <h1 style="margin-top:14px">{TAGLINE}</h1>
        <p class="lead">
          {BRAND} — гарант-сервис для безопасных переводов между незнакомыми людьми.
          Деньги покупателя удерживаются до подтверждения сделки. Если что-то пошло
          не так — арбитр решает спор.
        </p>
        <div class="cta-row">
          {bot_btn}
          <a class="btn ghost" href="#how">Как это работает</a>
        </div>
        <div class="stats">
          <div class="stat"><div class="num">{s['deals_total']}</div><div class="lbl">всего сделок</div></div>
          <div class="stat"><div class="num">{s['deals_completed']}</div><div class="lbl">успешно завершены</div></div>
          <div class="stat"><div class="num">{s['users']}</div><div class="lbl">пользователей</div></div>
          <div class="stat"><div class="num">{s['volume']:.0f}</div><div class="lbl">оборот, ₽</div></div>
        </div>
      </div>

      <div class="hero-card">
        <h3 style="margin-top:0">Войти в кабинет</h3>
        <p class="muted" style="margin-top:0">Откройте свой кабинет по Telegram ID. Узнать ID можно через бота — команда /id.</p>
        <form action="/user-redirect" method="post">
          <label>Ваш Telegram ID</label>
          <input type="number" name="user_id" placeholder="например, 123456789" required />
          <div style="margin-top:12px"><button class="btn" type="submit">{ICONS['user']} Открыть кабинет</button></div>
        </form>
        <hr style="border:0;border-top:1px solid var(--border);margin:18px 0" />
        <h3 style="margin:0">Открыть сделку по номеру</h3>
        <form action="/deal-redirect" method="post" style="margin-top:8px">
          <label>ID сделки</label>
          <input type="number" name="deal_id" placeholder="например, 42" required />
          <div style="margin-top:12px"><button class="btn ghost" type="submit">{ICONS['doc']} Перейти к сделке</button></div>
        </form>
      </div>
    </section>

    <section id="how" class="card">
      <h2>Как работает escrow</h2>
      <p class="muted" style="margin-top:0">Четыре шага. Без посредников. Деньги защищены на каждом этапе.</p>
      <div class="steps" style="margin-top:14px">
        <div class="step"><div class="n">1</div><h4>Создание сделки</h4><p>Продавец создаёт сделку и отправляет покупателю безопасную ссылку.</p></div>
        <div class="step"><div class="n">2</div><h4>Оплата покупателем</h4><p>Покупатель переводит сумму и отмечает оплату в боте.</p></div>
        <div class="step"><div class="n">3</div><h4>Подтверждение</h4><p>Гарант проверяет факт оплаты и удерживает средства до выдачи.</p></div>
        <div class="step"><div class="n">4</div><h4>Выплата продавцу</h4><p>После подтверждения средства поступают на баланс продавца.</p></div>
      </div>
    </section>

    <section class="features">
      <div class="feat">
        <div class="icon">{ICONS['shield']}</div>
        <h4>Escrow-удержание</h4>
        <p>Средства не уходят продавцу до подтверждения сделки. Покупатель защищён.</p>
      </div>
      <div class="feat">
        <div class="icon alt">{ICONS['scale']}</div>
        <h4>Арбитраж 24/7</h4>
        <p>Если возникает спор — гарант рассматривает доказательства и принимает решение.</p>
      </div>
      <div class="feat">
        <div class="icon warn">{ICONS['bolt']}</div>
        <h4>Без скрытых условий</h4>
        <p>Фиксированная комиссия, прозрачные статусы, видимая история действий.</p>
      </div>
      <div class="feat">
        <div class="icon">{ICONS['lock']}</div>
        <h4>Шифрование</h4>
        <p>Соединение защищено TLS. Реквизиты карты маскируются на стороне сервиса.</p>
      </div>
      <div class="feat">
        <div class="icon alt">{ICONS['user']}</div>
        <h4>Связка с Telegram</h4>
        <p>Привязка по Telegram ID — никаких лишних регистраций, паролей и почт.</p>
      </div>
      <div class="feat">
        <div class="icon warn">{ICONS['doc']}</div>
        <h4>История и логи</h4>
        <p>Каждое действие фиксируется. Сделки и споры можно открыть по ссылке.</p>
      </div>
    </section>

    <section class="card" id="security">
      <h2>Безопасность</h2>
      <div class="grid-2">
        <div>
          <h3>Что мы делаем</h3>
          <ul style="color:#c5cfdc; padding-left: 18px; margin: 6px 0">
            <li>Удерживаем средства до подтверждения исполнения сделки</li>
            <li>Маскируем номера карт в публичных страницах кабинета</li>
            <li>Логируем все действия с временной меткой</li>
            <li>Запрещаем сценарий «продавец = покупатель»</li>
            <li>Открытый процесс споров — обе стороны видят статус</li>
          </ul>
        </div>
        <div>
          <h3>Что не делает сервис</h3>
          <ul style="color:#c5cfdc; padding-left: 18px; margin: 6px 0">
            <li>Не запрашивает CVV, пароли или коды из СМС</li>
            <li>Не пишет первым пользователю с просьбой перевести средства</li>
            <li>Не работает в обход ссылок-сделок и Telegram-бота</li>
            <li>Не хранит платёжные данные третьих сторон</li>
          </ul>
        </div>
      </div>
    </section>
    """
    return HTMLResponse(page("Главная", body))


@app.post("/user-redirect")
async def user_redirect(user_id: int = Form(...)):
    return RedirectResponse(f"/user/{user_id}", status_code=303)


@app.post("/deal-redirect")
async def deal_redirect(deal_id: int = Form(...)):
    return RedirectResponse(f"/deal/{deal_id}", status_code=303)


@app.get("/user/{user_id}", response_class=HTMLResponse)
async def user_page(user_id: int):
    user = core.get_user(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден. Сначала /start в боте.")
    deals = core.list_user_deals(user_id)
    wallet = user.get("wallet")
    masked = ("*" * (len(wallet) - 4) + wallet[-4:]) if wallet else "не привязан"
    rows = "".join(
        f"<tr>"
        f"<td><b>#{d['id']}</b></td>"
        f"<td>{d['amount']:.2f}</td>"
        f"<td>{d['fee']:.2f}</td>"
        f"<td>{status_badge(d['status'])}</td>"
        f"<td>{'продавец' if d['seller_id']==user_id else 'покупатель'}</td>"
        f"<td><a class='btn small ghost' href='/deal/{d['id']}'>открыть</a></td>"
        f"</tr>"
        for d in deals
    ) or "<tr><td colspan='6' class='muted'>Сделок пока нет</td></tr>"
    body = f"""
    <h1>Кабинет</h1>
    <p class="muted">Telegram ID {user_id}{(' — @' + user['username']) if user.get('username') else ''}</p>
    <div class="grid-2">
      <div class="card">
        <h3>Профиль</h3>
        <div class="deal-meta">
          <div><span>Карта</span><b>{masked}</b></div>
          <div><span>Банк</span><b>{user.get('bank') or '—'}</b></div>
          <div><span>Баланс</span><b>{float(user.get('balance') or 0):.2f}</b></div>
          <div><span>Админ</span><b>{'да' if user.get('is_admin') else 'нет'}</b></div>
        </div>
      </div>
      <div class="card">
        <h3>Безопасность</h3>
        <p class="muted" style="margin-top:0">Управление кошельком и подтверждения — в Telegram-боте. Сайт показывает только статус и историю.</p>
        <div class="badges">
          <span class="chip">{ICONS['lock']} TLS</span>
          <span class="chip alt">{ICONS['shield']} Эскроу</span>
          <span class="chip">{ICONS['scale']} Арбитраж</span>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Мои сделки</h3>
      <table>
        <thead><tr><th>ID</th><th>Сумма</th><th>Комиссия</th><th>Статус</th><th>Роль</th><th></th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return HTMLResponse(page(f"Кабинет {user_id}", body))


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_page(deal_id: int):
    deal = core.get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    payout = max(0.0, deal['amount'] - deal['fee'])
    dispute_block = ""
    d = db.get_dispute_for_deal(deal_id)
    if d:
        dispute_block = f"""
        <div class="card">
          <h3>Спор по сделке</h3>
          <div class="deal-meta">
            <div><span>Открыл</span><b>{d['opened_by']}</b></div>
            <div><span>Статус спора</span><b>{d['status']}</b></div>
            <div><span>Причина</span><b>{d['reason']}</b></div>
            <div><span>Решение</span><b>{d.get('resolution') or '—'}</b></div>
          </div>
        </div>
        """
    bot = _bot_username()
    bot_link = f"https://t.me/{bot}?start=deal_{deal_id}" if bot else ""
    bot_block = f"""
    <div class="card">
      <h3>Действия</h3>
      <p class="muted" style="margin-top:0">Действия по сделке — через Telegram-бота. Это защищает от подделки и подтверждает участника.</p>
      {f'<a class="btn" href="{bot_link}" target="_blank">{ICONS["tg"]} Открыть сделку в боте</a>' if bot_link else ''}
    </div>
    """
    body = f"""
    <h1>Сделка #{deal['id']}</h1>
    <div class="badges" style="margin-bottom:14px">
      {status_badge(deal['status'])}
      <span class="chip">{ICONS['shield']} Защищено эскроу</span>
    </div>
    <div class="grid-2">
      <div class="card">
        <h3>Параметры сделки</h3>
        <div class="deal-meta">
          <div><span>Сумма</span><b>{deal['amount']:.2f}</b></div>
          <div><span>Комиссия</span><b>{deal['fee']:.2f}</b></div>
          <div><span>Продавец получит</span><b>{payout:.2f}</b></div>
          <div><span>Создана</span><b>{deal['created_at']}</b></div>
          <div><span>Обновлена</span><b>{deal['updated_at']}</b></div>
        </div>
      </div>
      <div class="card">
        <h3>Участники</h3>
        <div class="deal-meta">
          <div><span>Продавец</span><b><a href="/user/{deal['seller_id']}">ID {deal['seller_id']}</a></b></div>
          <div><span>Покупатель</span><b>{f'<a href="/user/{deal["buyer_id"]}">ID {deal["buyer_id"]}</a>' if deal['buyer_id'] else '—'}</b></div>
        </div>
      </div>
    </div>
    {dispute_block}
    {bot_block}
    """
    return HTMLResponse(page(f"Сделка #{deal_id}", body))


# ---------- админка ----------

def _check_admin(request: Request) -> None:
    token = request.cookies.get("admin_token") or request.query_params.get("token")
    if token != _admin_token():
        raise HTTPException(401, "Требуется вход в админку")


@app.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request):
    token = request.cookies.get("admin_token") or request.query_params.get("token")
    if token != _admin_token():
        body = f"""
        <div style="max-width:420px;margin:48px auto">
          <div class="card">
            <h2 style="margin-top:0">Вход в админ-панель</h2>
            <p class="muted" style="margin-top:0">Доступ только у уполномоченных арбитров.</p>
            <form action="/admin/login" method="post">
              <label>Пароль</label>
              <input type="password" name="token" required autofocus />
              <div style="margin-top:14px"><button class="btn" type="submit">{ICONS['key']} Войти</button></div>
            </form>
          </div>
        </div>
        """
        return HTMLResponse(page("Вход", body))

    s = _stats()
    deals = core.list_all_deals()
    users = core.list_all_users()
    disputes = core.list_all_disputes()
    logs = core.list_all_logs(50)

    deal_rows = "".join(
        f"<tr>"
        f"<td><b>#{d['id']}</b></td>"
        f"<td>{d['amount']:.2f}</td>"
        f"<td>{d['fee']:.2f}</td>"
        f"<td>{d['seller_id']}</td>"
        f"<td>{d['buyer_id'] or '—'}</td>"
        f"<td>{status_badge(d['status'])}</td>"
        f"<td class='actions'>{_deal_actions(d)}</td>"
        f"</tr>"
        for d in deals
    ) or "<tr><td colspan='7' class='muted'>Нет сделок</td></tr>"

    def _role_cell(u):
        return "<span class='badge completed'>админ</span>" if u.get("is_admin") else "—"

    user_rows = "".join(
        f"<tr>"
        f"<td>{u['id']}</td>"
        f"<td>{u.get('username') or '—'}</td>"
        f"<td>{(u.get('bank') or '—')}</td>"
        f"<td>{float(u.get('balance') or 0):.2f}</td>"
        f"<td>{_role_cell(u)}</td>"
        f"</tr>"
        for u in users
    ) or "<tr><td colspan='5' class='muted'>Нет пользователей</td></tr>"

    dispute_rows = "".join(
        f"<tr>"
        f"<td>#{x['id']}</td>"
        f"<td><a href='/deal/{x['deal_id']}'>#{x['deal_id']}</a></td>"
        f"<td>{x['opened_by']}</td>"
        f"<td>{x['reason']}</td>"
        f"<td>{x['status']}</td>"
        f"<td>{x.get('resolution') or '—'}</td>"
        f"</tr>"
        for x in disputes
    ) or "<tr><td colspan='6' class='muted'>Споров нет</td></tr>"

    log_rows = "".join(
        f"<tr><td>{l['timestamp']}</td><td>{l['action']}</td>"
        f"<td>{l.get('user_id') or '—'}</td><td>{l.get('details') or ''}</td></tr>"
        for l in logs
    ) or "<tr><td colspan='4' class='muted'>Логов нет</td></tr>"

    body = f"""
    <h1>Админ-панель</h1>
    <p class="muted">Управление сделками, пользователями и спорами.</p>
    <div class="stats" style="margin-bottom:18px">
      <div class="stat"><div class="num">{s['deals_total']}</div><div class="lbl">сделок</div></div>
      <div class="stat"><div class="num">{s['in_escrow']}</div><div class="lbl">в эскроу</div></div>
      <div class="stat"><div class="num">{s['deals_completed']}</div><div class="lbl">завершено</div></div>
      <div class="stat"><div class="num">{s['users']}</div><div class="lbl">пользователей</div></div>
    </div>

    <div class="card">
      <h3>Все сделки</h3>
      <table>
        <thead><tr><th>ID</th><th>Сумма</th><th>Комиссия</th><th>Продавец</th><th>Покупатель</th><th>Статус</th><th>Действия</th></tr></thead>
        <tbody>{deal_rows}</tbody>
      </table>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Пользователи</h3>
        <table>
          <thead><tr><th>ID</th><th>Username</th><th>Банк</th><th>Баланс</th><th>Роль</th></tr></thead>
          <tbody>{user_rows}</tbody>
        </table>
        <form action="/admin/grant" method="post" style="margin-top:14px">
          <label>Выдать админа (Telegram ID)</label>
          <input type="number" name="user_id" required />
          <div style="margin-top:10px"><button class="btn small" type="submit">{ICONS['shield']} Сделать админом</button></div>
        </form>
      </div>
      <div class="card">
        <h3>Споры</h3>
        <table>
          <thead><tr><th>ID</th><th>Сделка</th><th>Открыл</th><th>Причина</th><th>Статус</th><th>Решение</th></tr></thead>
          <tbody>{dispute_rows}</tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>Журнал действий</h3>
      <table>
        <thead><tr><th>Время</th><th>Действие</th><th>Пользователь</th><th>Детали</th></tr></thead>
        <tbody>{log_rows}</tbody>
      </table>
    </div>
    """
    return HTMLResponse(page("Админ-панель", body))


def _deal_actions(d: dict) -> str:
    deal_id = d["id"]
    parts = []
    if d["status"] == "paid":
        parts.append(
            f"<form action='/admin/confirm/{deal_id}' method='post'><button class='btn small'>Подтвердить оплату</button></form>"
        )
        parts.append(
            f"<form action='/admin/reject/{deal_id}' method='post'>"
            f"<input type='text' name='reason' placeholder='причина' />"
            f"<button class='btn small danger'>Отклонить</button></form>"
        )
    if d["status"] == "dispute":
        parts.append(
            f"<form action='/admin/resolve/{deal_id}' method='post'>"
            f"<input type='text' name='resolution' placeholder='комментарий' />"
            f"<button class='btn small' name='winner' value='seller'>Продавцу</button>"
            f"<button class='btn small danger' name='winner' value='buyer'>Покупателю</button></form>"
        )
    return "".join(parts) or "—"


@app.post("/admin/login")
async def admin_login(token: str = Form(...)):
    if token != _admin_token():
        raise HTTPException(401, "Неверный пароль")
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("admin_token", token, httponly=True, samesite="lax")
    return resp


@app.post("/admin/grant")
async def admin_grant(request: Request, user_id: int = Form(...)):
    _check_admin(request)
    core.grant_admin(int(user_id))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/confirm/{deal_id}")
async def admin_confirm(request: Request, deal_id: int):
    _check_admin(request)
    _ensure_web_admin()
    try:
        core.admin_confirm_payment(deal_id, 0)
    except core.CoreError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reject/{deal_id}")
async def admin_reject(request: Request, deal_id: int, reason: str = Form("")):
    _check_admin(request)
    _ensure_web_admin()
    try:
        core.admin_reject_payment(deal_id, 0, reason)
    except core.CoreError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/payout/{deal_id}")
async def admin_payout(request: Request, deal_id: int):
    _check_admin(request)
    _ensure_web_admin()
    try:
        core.admin_payout_seller(deal_id, 0)
    except core.CoreError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/resolve/{deal_id}")
async def admin_resolve(request: Request, deal_id: int, winner: str = Form(...), resolution: str = Form("")):
    _check_admin(request)
    _ensure_web_admin()
    try:
        core.resolve_dispute(deal_id, 0, winner, resolution)
    except core.CoreError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/admin", status_code=303)


def _ensure_web_admin() -> None:
    """Виртуальный пользователь-админ id=0 для действий из веб-админки."""
    u = db.get_user(0)
    if not u:
        db.upsert_user(0, "web_admin")
    if not (db.get_user(0) or {}).get("is_admin"):
        db.set_admin(0, True)
