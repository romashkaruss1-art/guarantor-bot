"""Telegram bot — премиальный UX, бизнес-логика в core.py."""
from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, BotCommand,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import core
import db

log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BRAND = "GUARANTOR"
HR = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬"


# ---------- FSM ----------
class WalletStates(StatesGroup):
    waiting_card = State()
    waiting_bank = State()


class DealStates(StatesGroup):
    waiting_amount = State()


class DisputeStates(StatesGroup):
    waiting_reason = State()


# ---------- клавиатура ----------
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Создать сделку"), KeyboardButton(text="💼 Мои сделки")],
        [KeyboardButton(text="👛 Кошелёк"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🌐 Сайт"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)

STATUS_META = {
    "created":           ("⚪️", "Ожидает покупателя"),
    "waiting_payment":   ("🟡", "Ожидает оплаты"),
    "paid":              ("🟠", "Оплачено · ждём гаранта"),
    "payment_confirmed": ("🔵", "Оплата подтверждена"),
    "goods_sent":        ("🟣", "Товар отправлен"),
    "dispute":           ("⚠️", "Открыт спор"),
    "completed":         ("✅", "Завершена"),
    "cancelled":         ("❌", "Отменена"),
}


# ---------- утилиты ----------
def _e(s) -> str:
    return html.escape(str(s) if s is not None else "")


def _site_base() -> str:
    return os.environ.get("PUBLIC_BASE_URL") or (
        f"https://{os.environ['REPLIT_DEV_DOMAIN']}"
        if os.environ.get("REPLIT_DEV_DOMAIN") else ""
    )


def _site_kb(deal_id: Optional[int] = None) -> Optional[InlineKeyboardMarkup]:
    base = _site_base()
    if not base:
        return None
    rows = [[InlineKeyboardButton(text="🌐 Открыть сайт", url=base)]]
    if deal_id is not None:
        rows.append([InlineKeyboardButton(text=f"🔗 Сделка #{deal_id} на сайте", url=f"{base}/deal/{deal_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _progress(status: str) -> str:
    completed = {"completed"}
    paid_or_after = {"paid", "payment_confirmed", "goods_sent", "completed"}
    confirmed_or_after = {"payment_confirmed", "goods_sent", "completed"}
    sent_or_after = {"goods_sent", "completed"}
    has_buyer = {"waiting_payment", "paid", "payment_confirmed", "goods_sent", "completed", "dispute"}
    steps = [
        ("Покупатель присоединился", status in has_buyer),
        ("Оплата отмечена покупателем", status in paid_or_after),
        ("Гарант подтвердил оплату",   status in confirmed_or_after),
        ("Товар отправлен продавцом",  status in sent_or_after),
        ("Получение подтверждено",     status in completed),
    ]
    out, marked = [], False
    for label, done in steps:
        if done:
            out.append(f"   ✅  <i>{label}</i>")
        elif not marked:
            marked = True
            out.append(f"   🔵  <b>{label}</b>  ← <i>сейчас</i>")
        else:
            out.append(f"   ⚪️  {label}")
    return "\n".join(out)


def _format_deal(d: dict) -> str:
    icon, status_ru = STATUS_META.get(d["status"], ("•", d["status"]))
    payout = max(0.0, d['amount'] - d['fee'])
    txt = (
        f"💼 <b>СДЕЛКА</b> <code>#{d['id']}</code>\n"
        f"<i>{HR}</i>\n"
        f"💰 <b>Сумма:</b>      <code>{d['amount']:.2f} ₽</code>\n"
        f"⚙️ <b>Комиссия:</b>  <code>{d['fee']:.2f} ₽</code>\n"
        f"🏦 <b>К выплате:</b>  <code>{payout:.2f} ₽</code>\n"
        f"<i>{HR}</i>\n"
        f"👤 <b>Продавец:</b>   <code>{d['seller_id']}</code>\n"
        f"🛒 <b>Покупатель:</b> <code>{d['buyer_id'] or '—'}</code>\n"
        f"{icon} <b>Статус:</b>     <i>{_e(status_ru)}</i>"
    )
    if d["status"] != "cancelled":
        txt += f"\n<i>{HR}</i>\n📊 <b>ПРОГРЕСС</b>\n{_progress(d['status'])}"
    return txt


def _deal_action_kb(deal: dict, viewer_id: int) -> Optional[InlineKeyboardMarkup]:
    rows = []
    status, deal_id = deal["status"], deal["id"]
    is_buyer = viewer_id == deal.get("buyer_id")
    is_seller = viewer_id == deal.get("seller_id")
    if is_buyer and status == core.STATUS_WAITING_PAYMENT:
        rows.append([InlineKeyboardButton(text="💸 Сообщить об оплате", callback_data=f"pay:{deal_id}")])
    if is_seller and status == core.STATUS_PAYMENT_CONFIRMED:
        rows.append([InlineKeyboardButton(text="📦 Подтвердить отправку", callback_data=f"ship:{deal_id}")])
    if is_buyer and status == core.STATUS_GOODS_SENT:
        rows.append([InlineKeyboardButton(text="✅ Подтвердить получение", callback_data=f"recv:{deal_id}")])
    if (is_buyer or is_seller) and deal.get("buyer_id") and status in core.ACTIVE_STATUSES:
        rows.append([InlineKeyboardButton(text="⚠️ Открыть спор", callback_data=f"disp:{deal_id}")])
    base = _site_base()
    if base:
        rows.append([InlineKeyboardButton(text=f"🔗 Сделка #{deal_id} на сайте", url=f"{base}/deal/{deal_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _deals_list_kb(deals: list) -> Optional[InlineKeyboardMarkup]:
    rows = []
    for d in deals[:20]:
        icon, label = STATUS_META.get(d["status"], ("•", d["status"]))
        rows.append([InlineKeyboardButton(
            text=f"{icon} Сделка #{d['id']} · {d['amount']:.0f}₽ [{label}]",
            callback_data=f"info:{d['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _user_stats(user_id: int) -> dict:
    deals = core.list_user_deals(user_id)
    total = len(deals)
    completed = sum(1 for d in deals if d["status"] == "completed")
    cancelled = sum(1 for d in deals if d["status"] in ("cancelled",))
    active = sum(1 for d in deals if d["status"] in core.ACTIVE_STATUSES)
    finished = completed + cancelled
    rating = (completed / finished * 5) if finished else 0.0
    return {"total": total, "completed": completed, "active": active,
            "cancelled": cancelled, "rating": rating}


def _stars(rating: float) -> str:
    full = int(rating)
    half = 1 if rating - full >= 0.5 else 0
    empty = 5 - full - half
    return "⭐️" * full + ("✨" if half else "") + "☆" * empty


# ---------- диспетчер ----------
def build_dispatcher(bot: Bot) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart(deep_link=True))
    async def start_with_payload(message: Message, command: CommandObject):
        core.register_user(message.from_user.id, message.from_user.username)
        payload = (command.args or "").strip()
        if payload.startswith("deal_"):
            try:
                deal_id = int(payload.split("_", 1)[1])
            except (ValueError, IndexError):
                await message.answer("⚠️ <b>Некорректная ссылка на сделку</b>")
                return
            try:
                deal = core.join_deal(deal_id, message.from_user.id)
            except core.CoreError as e:
                await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>")
                return
            await message.answer(
                f"🎯 <b>Вы вошли в сделку как покупатель</b>\n\n"
                f"{_format_deal(deal)}\n\n"
                f"💡 <i>Когда переведёте средства продавцу — нажмите кнопку ниже.</i>",
                reply_markup=_deal_action_kb(deal, message.from_user.id),
            )
            return
        if payload.startswith("u_"):
            await message.answer(
                f"👤 <b>Профиль пользователя</b>\n<i>{HR}</i>\n"
                f"🆔 <code>{_e(payload[2:])}</code>\n\n"
                "💼 <i>Создавайте сделки и работайте безопасно через гаранта.</i>",
                reply_markup=MAIN_KB,
            )
            return
        await cmd_start(message)

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        core.register_user(message.from_user.id, message.from_user.username)
        site = _site_base()
        site_line = f"\n🌐 <b>Сайт:</b> {site}\n" if site else ""
        text = (
            f"✨  <b>{BRAND}</b>  ✨\n"
            f"<i>P2P escrow с гарантом</i>\n"
            f"<i>{HR}</i>\n"
            "🛡 <b>Безопасные сделки</b> между незнакомыми людьми.\n"
            "Средства покупателя удерживаются гарантом до подтверждения сделки. "
            "При спорах решение принимает арбитр."
            f"{site_line}"
            f"<i>{HR}</i>\n"
            "📋 <b>КАК ЭТО РАБОТАЕТ</b>\n"
            "  ①  Продавец создаёт сделку и шлёт ссылку\n"
            "  ②  Покупатель оплачивает и сообщает об этом\n"
            "  ③  Гарант подтверждает поступление средств\n"
            "  ④  Продавец передаёт товар\n"
            "  ⑤  Покупатель подтверждает получение\n"
            "  ⑥  Сделка закрыта, выплата продавцу\n"
            f"<i>{HR}</i>\n"
            "👇 <i>Все действия — кнопками внизу.</i>"
        )
        await message.answer(text, reply_markup=MAIN_KB)
        kb = _site_kb()
        if kb:
            await message.answer("🌐 <b>Открыть полный кабинет на сайте:</b>", reply_markup=kb)

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await cmd_start(message)

    @dp.message(Command("id"))
    async def cmd_id(message: Message):
        await message.answer(
            f"🆔 <b>Ваш Telegram ID:</b> <code>{message.from_user.id}</code>\n\n"
            "<b>Чтобы стать админом:</b>\n"
            "1️⃣  Откройте сайт → раздел <code>/admin</code>\n"
            "2️⃣  Пароль по умолчанию: <code>admin</code>\n"
            "3️⃣  Введите этот ID в поле «Выдать админа»",
            reply_markup=MAIN_KB,
        )

    @dp.message(Command("site"))
    async def cmd_site(message: Message):
        await _send_site(message)

    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if not core.is_admin(message.from_user.id):
            return
        base = _site_base()
        url = f"{base}/admin" if base else "/admin"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Открыть админ-панель", url=url)]
        ]) if base else None
        await message.answer(
            f"🔐 <b>АДМИН-ПАНЕЛЬ</b>\n<i>{HR}</i>\n"
            f"📍 <b>Адрес:</b> <code>{_e(url)}</code>\n\n"
            "<i>Войдите по паролю и управляйте сделками, спорами и пользователями.</i>",
            reply_markup=kb,
        )

    @dp.message(F.text == "🌐 Сайт")
    async def btn_site(message: Message):
        await _send_site(message)

    async def _send_site(message: Message):
        base = _site_base()
        if not base:
            await message.answer("⚠️ <b>Сайт временно недоступен.</b> <i>Попробуйте позже.</i>")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главная", url=base)],
            [InlineKeyboardButton(text="👤 Мой кабинет", url=f"{base}/user/{message.from_user.id}")],
        ])
        await message.answer(
            f"🌐 <b>{BRAND}</b> — <i>официальный сайт</i>\n<i>{HR}</i>\n"
            f"🏠 <b>Главная:</b>  <code>{_e(base)}</code>\n"
            f"👤 <b>Кабинет:</b>  <code>{_e(base)}/user/{message.from_user.id}</code>\n\n"
            "📊 <i>На сайте — статусы, история и параметры профиля.</i>\n"
            "🔒 <i>Все действия по сделкам — только через бот для безопасности.</i>",
            reply_markup=kb,
        )

    @dp.message(F.text == "❓ Помощь")
    async def btn_help(message: Message):
        await cmd_start(message)

    @dp.message(F.text == "👛 Кошелёк")
    async def btn_wallet(message: Message, state: FSMContext):
        await cmd_wallet(message, state)

    @dp.message(F.text == "👤 Профиль")
    async def btn_me(message: Message):
        await cmd_me(message)

    @dp.message(F.text == "💼 Мои сделки")
    async def btn_deals(message: Message):
        await cmd_deals(message)

    @dp.message(F.text == "➕ Создать сделку")
    async def btn_create_deal(message: Message, state: FSMContext):
        core.register_user(message.from_user.id, message.from_user.username)
        await state.set_state(DealStates.waiting_amount)
        await message.answer(
            f"➕ <b>СОЗДАНИЕ СДЕЛКИ</b>\n<i>{HR}</i>\n"
            "💰 <b>Введите сумму сделки в рублях:</b>"
        )

    # ---------- кошелёк ----------
    @dp.message(Command("wallet"))
    async def cmd_wallet(message: Message, state: FSMContext):
        await state.set_state(WalletStates.waiting_card)
        await message.answer(
            f"👛 <b>ПРИВЯЗКА КОШЕЛЬКА</b>\n<i>{HR}</i>\n"
            "<b>Шаг 1 из 2</b> — введите номер карты <i>(только цифры)</i>.\n"
            "🔒 <i>Данные используются только для отображения вам и контрагенту.</i>"
        )

    @dp.message(WalletStates.waiting_card)
    async def wallet_card(message: Message, state: FSMContext):
        await state.update_data(card=(message.text or "").strip())
        await state.set_state(WalletStates.waiting_bank)
        await message.answer(
            "<b>Шаг 2 из 2</b> — 🏦 укажите банк "
            "<i>(например: Сбербанк, Тинькофф, Альфа)</i>."
        )

    @dp.message(WalletStates.waiting_bank)
    async def wallet_bank(message: Message, state: FSMContext):
        data = await state.get_data()
        card = data.get("card", "")
        bank = (message.text or "").strip()
        try:
            core.bind_wallet(message.from_user.id, card, bank)
        except core.CoreError as e:
            await state.clear()
            await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>\n\n🔁 Запустите /wallet заново.")
            return
        await state.clear()
        u = core.get_user(message.from_user.id) or {}
        masked = "•••• " + (u.get("wallet") or "")[-4:]
        await message.answer(
            f"✅ <b>Кошелёк успешно привязан!</b>\n<i>{HR}</i>\n"
            f"💳 <b>Карта:</b> <code>{_e(masked)}</code>\n"
            f"🏦 <b>Банк:</b>  <i>{_e(u.get('bank') or '')}</i>"
        )

    @dp.message(Command("me"))
    async def cmd_me(message: Message):
        u = core.get_user(message.from_user.id) or {}
        wallet = u.get("wallet")
        masked = ("•" * (len(wallet) - 4) + wallet[-4:]) if wallet else "не привязан"
        st = _user_stats(message.from_user.id)
        base = _site_base()
        bot_name = core.BOT_USERNAME
        rows = []
        if bot_name:
            share_url = f"https://t.me/{bot_name}?start=u_{message.from_user.id}"
            rows.append([InlineKeyboardButton(
                text="📤 Поделиться профилем",
                switch_inline_query=share_url,
            )])
            rows.append([InlineKeyboardButton(text="🔗 Ссылка на профиль", url=share_url)])
        if base:
            rows.append([InlineKeyboardButton(
                text="🌐 Открыть кабинет на сайте",
                url=f"{base}/user/{message.from_user.id}",
            )])
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        role = "👑 админ" if u.get("is_admin") else "👤 пользователь"
        await message.answer(
            f"👤 <b>ПРОФИЛЬ</b>\n<i>{HR}</i>\n"
            f"🆔 <b>ID:</b>      <code>{message.from_user.id}</code>\n"
            f"💳 <b>Карта:</b>   <code>{_e(masked)}</code>\n"
            f"🏦 <b>Банк:</b>    <i>{_e(u.get('bank') or '—')}</i>\n"
            f"💰 <b>Баланс:</b>  <code>{float(u.get('balance') or 0):.2f} ₽</code>\n"
            f"🎖 <b>Роль:</b>    {role}\n"
            f"<i>{HR}</i>\n"
            f"📊 <b>СТАТИСТИКА</b>\n"
            f"  ✅  Завершено:  <b>{st['completed']}</b>\n"
            f"  🔄  В процессе: <b>{st['active']}</b>\n"
            f"  ❌  Отменено:   <b>{st['cancelled']}</b>\n"
            f"  📈  Всего:       <b>{st['total']}</b>\n"
            f"<i>{HR}</i>\n"
            f"⭐️ <b>Рейтинг:</b> {_stars(st['rating'])}  <code>{st['rating']:.2f}/5.00</code>",
            reply_markup=kb,
        )

    # ---------- сделки ----------
    @dp.message(Command("deal"))
    async def cmd_deal(message: Message, command: CommandObject, state: FSMContext):
        core.register_user(message.from_user.id, message.from_user.username)
        arg = (command.args or "").strip()
        if not arg:
            await state.set_state(DealStates.waiting_amount)
            await message.answer(
                f"➕ <b>СОЗДАНИЕ СДЕЛКИ</b>\n<i>{HR}</i>\n"
                "💰 <b>Введите сумму сделки в рублях:</b>"
            )
            return
        await _create_deal(message, arg)

    @dp.message(DealStates.waiting_amount)
    async def deal_amount(message: Message, state: FSMContext):
        await state.clear()
        await _create_deal(message, (message.text or "").strip())

    async def _create_deal(message: Message, amount_str: str):
        try:
            deal = core.create_deal(message.from_user.id, float(amount_str.replace(",", ".")))
        except (ValueError, TypeError):
            await message.answer("⚠️ <b>Сумма должна быть числом</b>")
            return
        except core.CoreError as e:
            await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>")
            return
        link = core.deal_link(deal["id"])
        base = _site_base()
        rows = [[InlineKeyboardButton(text="📤 Отправить покупателю", switch_inline_query=link)]]
        if base:
            rows.append([InlineKeyboardButton(text=f"🔗 Сделка #{deal['id']} на сайте", url=f"{base}/deal/{deal['id']}")])
        await message.answer(
            f"🎉 <b>СДЕЛКА СОЗДАНА</b>\n<i>{HR}</i>\n\n"
            f"{_format_deal(deal)}\n\n"
            f"<i>{HR}</i>\n"
            f"🔗 <b>Ссылка для покупателя:</b>\n<code>{_e(link)}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @dp.message(Command("deals"))
    async def cmd_deals(message: Message):
        deals = core.list_user_deals(message.from_user.id)
        if not deals:
            await message.answer(
                f"📭 <b>У вас пока нет сделок</b>\n<i>{HR}</i>\n"
                "👇 <i>Нажмите «➕ Создать сделку», чтобы начать.</i>"
            )
            return
        await message.answer(
            f"💼 <b>МОИ СДЕЛКИ</b> · <code>{len(deals)}</code>\n<i>{HR}</i>\n"
            "👇 <i>Нажмите на сделку, чтобы увидеть подробности.</i>",
            reply_markup=_deals_list_kb(deals),
        )

    @dp.callback_query(F.data.startswith("info:"))
    async def cb_info(call: CallbackQuery):
        deal_id = int(call.data.split(":", 1)[1])
        deal = core.get_deal(deal_id)
        if not deal:
            await call.answer("Сделка не найдена", show_alert=True)
            return
        await call.answer()
        await call.message.answer(_format_deal(deal), reply_markup=_deal_action_kb(deal, call.from_user.id))

    @dp.message(Command("deal_info"))
    async def cmd_deal_info(message: Message, command: CommandObject):
        try:
            deal_id = int((command.args or "").strip())
        except (TypeError, ValueError):
            await message.answer("ℹ️ <b>Использование:</b> <code>/deal_info &lt;id&gt;</code>")
            return
        deal = core.get_deal(deal_id)
        if not deal:
            await message.answer("⚠️ <b>Сделка не найдена</b>")
            return
        await message.answer(_format_deal(deal), reply_markup=_deal_action_kb(deal, message.from_user.id))

    @dp.message(F.text.regexp(r"^/paid_(\d+)$"))
    async def cmd_paid(message: Message):
        try:
            deal_id = int(message.text.split("_", 1)[1])
        except (ValueError, IndexError):
            return
        try:
            deal = core.buyer_mark_paid(deal_id, message.from_user.id)
        except core.CoreError as e:
            await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>")
            return
        await message.answer(
            f"💸 <b>Оплата отмечена</b>\n<i>{HR}</i>\n"
            f"⏳ <i>Гарант проверит поступление и подтвердит сделку.</i>\n\n"
            f"{_format_deal(deal)}",
            reply_markup=_deal_action_kb(deal, message.from_user.id),
        )

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message, command: CommandObject):
        try:
            deal_id = int((command.args or "").strip())
        except (TypeError, ValueError):
            await message.answer("ℹ️ <b>Использование:</b> <code>/cancel &lt;id&gt;</code>")
            return
        try:
            deal = core.cancel_deal(deal_id, message.from_user.id)
        except core.CoreError as e:
            await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>")
            return
        await message.answer(
            f"❌ <b>Сделка отменена</b>\n<i>{HR}</i>\n\n{_format_deal(deal)}"
        )

    # ---------- споры ----------
    @dp.message(Command("dispute"))
    async def cmd_dispute(message: Message, command: CommandObject, state: FSMContext):
        try:
            deal_id = int((command.args or "").strip())
        except (TypeError, ValueError):
            await message.answer("ℹ️ <b>Использование:</b> <code>/dispute &lt;id&gt;</code>")
            return
        deal = core.get_deal(deal_id)
        if not deal:
            await message.answer("⚠️ <b>Сделка не найдена</b>")
            return
        await state.set_state(DisputeStates.waiting_reason)
        await state.update_data(deal_id=deal_id)
        await message.answer(
            f"⚠️ <b>ОТКРЫТИЕ СПОРА</b>\n<i>{HR}</i>\n"
            "✍️ <i>Опишите причину спора как можно подробнее — это поможет арбитру принять справедливое решение.</i>"
        )

    @dp.message(DisputeStates.waiting_reason)
    async def dispute_reason(message: Message, state: FSMContext):
        data = await state.get_data()
        deal_id = data.get("deal_id")
        await state.clear()
        try:
            deal = core.open_dispute(int(deal_id), message.from_user.id, message.text or "")
        except core.CoreError as e:
            await message.answer(f"❌ <b>Ошибка:</b> <i>{_e(e)}</i>")
            return
        await message.answer(
            f"⚠️ <b>Спор открыт</b>\n<i>{HR}</i>\n"
            f"⏳ <i>Ожидайте решения арбитра.</i>\n\n{_format_deal(deal)}",
            reply_markup=_site_kb(int(deal_id)),
        )

    # ---------- inline-кнопки сделки ----------
    @dp.callback_query(F.data.startswith("pay:"))
    async def cb_pay(call: CallbackQuery):
        deal_id = int(call.data.split(":", 1)[1])
        try:
            deal = core.buyer_mark_paid(deal_id, call.from_user.id)
        except core.CoreError as e:
            await call.answer(str(e), show_alert=True)
            return
        await call.answer("💸 Оплата отмечена")
        await call.message.answer(
            f"💸 <b>Вы сообщили об оплате</b>\n<i>{HR}</i>\n"
            f"⏳ <i>Гарант проверит и подтвердит.</i>\n\n{_format_deal(deal)}",
            reply_markup=_deal_action_kb(deal, call.from_user.id),
        )

    @dp.callback_query(F.data.startswith("ship:"))
    async def cb_ship(call: CallbackQuery):
        deal_id = int(call.data.split(":", 1)[1])
        try:
            deal = core.seller_mark_goods_sent(deal_id, call.from_user.id)
        except core.CoreError as e:
            await call.answer(str(e), show_alert=True)
            return
        await call.answer("📦 Отправка отмечена")
        await call.message.answer(
            f"📦 <b>Вы отметили отправку товара</b>\n<i>{HR}</i>\n"
            f"⏳ <i>Ожидайте подтверждения покупателем.</i>\n\n{_format_deal(deal)}",
            reply_markup=_deal_action_kb(deal, call.from_user.id),
        )

    @dp.callback_query(F.data.startswith("recv:"))
    async def cb_recv(call: CallbackQuery):
        deal_id = int(call.data.split(":", 1)[1])
        try:
            deal = core.buyer_confirm_receipt(deal_id, call.from_user.id)
        except core.CoreError as e:
            await call.answer(str(e), show_alert=True)
            return
        await call.answer("🎉 Сделка завершена!")
        await call.message.answer(
            f"🎉 <b>СДЕЛКА УСПЕШНО ЗАВЕРШЕНА</b>\n"
            f"<i>{HR}</i>\n"
            f"✨ <i>Спасибо за использование {BRAND}!</i>\n"
            f"<i>{HR}</i>\n\n{_format_deal(deal)}",
            reply_markup=_deal_action_kb(deal, call.from_user.id),
        )

    @dp.callback_query(F.data.startswith("disp:"))
    async def cb_dispute(call: CallbackQuery, state: FSMContext):
        deal_id = int(call.data.split(":", 1)[1])
        deal = core.get_deal(deal_id)
        if not deal:
            await call.answer("Сделка не найдена", show_alert=True)
            return
        if call.from_user.id not in (deal.get("seller_id"), deal.get("buyer_id")):
            await call.answer("Спор может открыть только участник сделки", show_alert=True)
            return
        if deal["status"] not in core.ACTIVE_STATUSES:
            await call.answer("По этой сделке спор уже невозможен", show_alert=True)
            return
        await state.set_state(DisputeStates.waiting_reason)
        await state.update_data(deal_id=deal_id)
        await call.answer()
        await call.message.answer(
            f"⚠️ <b>ОТКРЫТИЕ СПОРА</b> · <code>#{deal_id}</code>\n<i>{HR}</i>\n"
            "✍️ <i>Опишите причину спора как можно подробнее — это поможет арбитру принять справедливое решение.</i>"
        )

    return dp


# ---------- уведомления ----------
async def _notification_loop(bot: Bot):
    queue = core.get_notify_queue()
    while True:
        item = await queue.get()
        if len(item) == 3:
            user_id, text, deal_id = item
        else:
            user_id, text = item
            deal_id = None
        kb = None
        if deal_id is not None:
            deal = core.get_deal(deal_id)
            if deal:
                kb = _deal_action_kb(deal, user_id)
        try:
            await bot.send_message(user_id, f"🔔 <i>{html.escape(text)}</i>", reply_markup=kb)
        except Exception as e:
            log.warning("notify failed for %s: %s", user_id, e)


async def run_bot():
    if not TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан — бот не запущен")
        return
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    core.set_bot_username(me.username or "")
    log.info("Bot started as @%s", me.username)
    try:
        await bot.set_my_commands([
            BotCommand(command="start",     description="🏠 Главная"),
            BotCommand(command="deal",      description="➕ Создать сделку"),
            BotCommand(command="deals",     description="💼 Мои сделки"),
            BotCommand(command="wallet",    description="👛 Привязать карту"),
            BotCommand(command="me",        description="👤 Профиль и баланс"),
            BotCommand(command="site",      description="🌐 Открыть сайт"),
            BotCommand(command="id",        description="🆔 Мой Telegram ID"),
            BotCommand(command="help",      description="❓ Помощь"),
        ])
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)
    dp = build_dispatcher(bot)
    notif_task = asyncio.create_task(_notification_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        notif_task.cancel()
        await bot.session.close()
