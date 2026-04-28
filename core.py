"""Вся бизнес-логика escrow-сервиса. Бот и веб обращаются ТОЛЬКО сюда."""
from __future__ import annotations

import os
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable

import db

# ---------- настройки ----------
COMMISSION_RATE = float(os.environ.get("COMMISSION_RATE", "0.05"))  # 5% комиссия
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
BOT_USERNAME = ""  # выставляется ботом при старте

# Очередь уведомлений: бот её слушает и шлёт сообщения пользователям
_notify_queue: "asyncio.Queue[tuple[int, str]]" = asyncio.Queue()


def set_bot_username(username: str) -> None:
    global BOT_USERNAME
    BOT_USERNAME = username


def get_notify_queue() -> "asyncio.Queue[tuple[int, str]]":
    return _notify_queue


def _notify(user_id: Optional[int], text: str, deal_id: Optional[int] = None) -> None:
    """Поставить уведомление в очередь. Если передан deal_id — бот прикрепит к сообщению
    кнопки действий по этой сделке для данного получателя."""
    if not user_id:
        return
    try:
        _notify_queue.put_nowait((user_id, text, deal_id))
    except Exception:
        pass


# ---------- статусы ----------
STATUS_CREATED = "created"
STATUS_WAITING_PAYMENT = "waiting_payment"
STATUS_PAID = "paid"
STATUS_PAYMENT_CONFIRMED = "payment_confirmed"
STATUS_GOODS_SENT = "goods_sent"
STATUS_DISPUTE = "dispute"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = [
    STATUS_CREATED,
    STATUS_WAITING_PAYMENT,
    STATUS_PAID,
    STATUS_PAYMENT_CONFIRMED,
    STATUS_GOODS_SENT,
    STATUS_DISPUTE,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
]

ACTIVE_STATUSES = (
    STATUS_CREATED,
    STATUS_WAITING_PAYMENT,
    STATUS_PAID,
    STATUS_PAYMENT_CONFIRMED,
    STATUS_GOODS_SENT,
)


class CoreError(Exception):
    pass


# ---------- пользователи ----------

def register_user(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    user = db.upsert_user(user_id, username)
    db.add_log("register", f"user {user_id}", user_id)
    return user


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    return db.get_user(user_id)


def bind_wallet(user_id: int, card: str, bank: str) -> Dict[str, Any]:
    """Привязка кошелька (карта + банк). Банк обязателен."""
    card = (card or "").strip()
    bank = (bank or "").strip()
    if not card:
        raise CoreError("Не указан номер карты")
    digits = card.replace(" ", "").replace("-", "")
    if not digits.isdigit() or not (12 <= len(digits) <= 19):
        raise CoreError("Некорректный номер карты")
    if not bank:
        raise CoreError("Банк обязателен. Без банка кошелёк не принимается.")
    db.upsert_user(user_id, None)
    db.set_wallet(user_id, digits, bank)
    db.add_log("bind_wallet", f"card={digits[-4:].rjust(len(digits), '*')} bank={bank}", user_id)
    return db.get_user(user_id)


def list_user_deals(user_id: int) -> List[Dict[str, Any]]:
    return db.list_user_deals(user_id)


# ---------- сделки ----------

def create_deal(seller_id: int, amount: float) -> Dict[str, Any]:
    user = db.get_user(seller_id)
    if not user:
        raise CoreError("Сначала зарегистрируйтесь /start")
    if not user.get("wallet") or not user.get("bank"):
        raise CoreError("Сначала привяжите кошелёк (карта + банк)")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise CoreError("Сумма должна быть числом")
    if amount <= 0:
        raise CoreError("Сумма должна быть больше нуля")
    fee = round(amount * COMMISSION_RATE, 2)
    deal_id = db.create_deal(seller_id, amount, fee)
    db.add_log("deal_create", f"deal #{deal_id} amount={amount} fee={fee}", seller_id)
    _notify(seller_id, f"Сделка #{deal_id} создана. Сумма {amount:.2f}, комиссия {fee:.2f}.\nСсылка: {deal_link(deal_id)}")
    return db.get_deal(deal_id)


def deal_link(deal_id: int) -> str:
    """Ссылка для входа покупателя в сделку (если username бота известен — даём deeplink)."""
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=deal_{deal_id}"
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL.rstrip('/')}/deal/{deal_id}"
    return f"/deal/{deal_id}"


def get_deal(deal_id: int) -> Optional[Dict[str, Any]]:
    return db.get_deal(deal_id)


def join_deal(deal_id: int, buyer_id: int) -> Dict[str, Any]:
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["seller_id"] == buyer_id:
        raise CoreError("Продавец не может быть покупателем в своей же сделке")
    if deal["buyer_id"] and deal["buyer_id"] != buyer_id:
        raise CoreError("В сделке уже есть другой покупатель")
    if deal["status"] not in (STATUS_CREATED, STATUS_WAITING_PAYMENT):
        raise CoreError(f"Нельзя войти в сделку в статусе '{deal['status']}'")
    db.upsert_user(buyer_id, None)
    if deal["buyer_id"] != buyer_id:
        db.set_buyer(deal_id, buyer_id)
        db.add_log("deal_join", f"deal #{deal_id} buyer {buyer_id}", buyer_id)
        _notify(deal["seller_id"], f"В сделку #{deal_id} вошёл покупатель {buyer_id}.", deal_id)
        _notify(buyer_id, f"Вы вошли в сделку #{deal_id}. Сумма {deal['amount']:.2f}. Когда переведёте деньги — нажмите кнопку ниже.", deal_id)
    return db.get_deal(deal_id)


def buyer_mark_paid(deal_id: int, buyer_id: int) -> Dict[str, Any]:
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["buyer_id"] != buyer_id:
        raise CoreError("Вы не покупатель этой сделки")
    if deal["status"] != STATUS_WAITING_PAYMENT:
        raise CoreError(f"Нельзя оплатить в статусе '{deal['status']}'")
    db.update_deal_status(deal_id, STATUS_PAID)
    db.add_log("buyer_paid", f"deal #{deal_id}", buyer_id)
    _notify(deal["seller_id"], f"Покупатель отметил оплату по сделке #{deal_id}. Ожидайте подтверждения админом.")
    _notify(buyer_id, f"Вы отметили оплату сделки #{deal_id}. Ожидайте подтверждения.")
    # уведомим админов
    for admin in [u for u in db.list_users() if u.get("is_admin")]:
        _notify(admin["id"], f"Сделка #{deal_id}: покупатель отметил оплату. Подтвердите в админке.")
    return db.get_deal(deal_id)


def admin_confirm_payment(deal_id: int, admin_id: int) -> Dict[str, Any]:
    """Админ подтвердил, что деньги от покупателя пришли. Ждём отправки товара."""
    _require_admin(admin_id)
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["status"] != STATUS_PAID:
        raise CoreError(f"Подтверждение возможно только в статусе 'paid', сейчас '{deal['status']}'")
    db.update_deal_status(deal_id, STATUS_PAYMENT_CONFIRMED)
    db.add_log("admin_confirm", f"deal #{deal_id}", admin_id)
    _notify(deal["seller_id"], f"Админ подтвердил оплату по сделке #{deal_id}. Передайте товар покупателю и нажмите кнопку ниже.", deal_id)
    _notify(deal["buyer_id"], f"Админ подтвердил вашу оплату по сделке #{deal_id}. Ожидайте отправку товара продавцом.", deal_id)
    return db.get_deal(deal_id)


def seller_mark_goods_sent(deal_id: int, seller_id: int) -> Dict[str, Any]:
    """Продавец отметил, что отправил товар."""
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["seller_id"] != seller_id:
        raise CoreError("Это действие доступно только продавцу")
    if deal["status"] != STATUS_PAYMENT_CONFIRMED:
        raise CoreError(f"Сейчас отметить отправку нельзя (статус '{deal['status']}')")
    db.update_deal_status(deal_id, STATUS_GOODS_SENT)
    db.add_log("seller_shipped", f"deal #{deal_id}", seller_id)
    _notify(deal["buyer_id"], f"Продавец отметил, что отправил товар по сделке #{deal_id}. Когда получите — нажмите кнопку ниже.", deal_id)
    _notify(seller_id, f"Вы отметили отправку товара по сделке #{deal_id}. Ожидайте подтверждения покупателем.", deal_id)
    return db.get_deal(deal_id)


def buyer_confirm_receipt(deal_id: int, buyer_id: int) -> Dict[str, Any]:
    """Покупатель подтвердил получение — сделка завершается, выплата продавцу."""
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["buyer_id"] != buyer_id:
        raise CoreError("Это действие доступно только покупателю")
    if deal["status"] != STATUS_GOODS_SENT:
        raise CoreError(f"Подтвердить получение можно только после отправки товара (статус '{deal['status']}')")
    payout = round(deal["amount"] - deal["fee"], 2)
    db.add_balance(deal["seller_id"], payout)
    db.update_deal_status(deal_id, STATUS_COMPLETED)
    db.add_log("buyer_received", f"deal #{deal_id} payout={payout}", buyer_id)
    _notify(deal["seller_id"], f"Покупатель подтвердил получение товара по сделке #{deal_id}. На баланс зачислено {payout:.2f}.")
    _notify(buyer_id, f"Сделка #{deal_id} успешно завершена. Спасибо!")
    return db.get_deal(deal_id)


def admin_reject_payment(deal_id: int, admin_id: int, reason: str = "") -> Dict[str, Any]:
    _require_admin(admin_id)
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["status"] != STATUS_PAID:
        raise CoreError(f"Отклонить можно только в статусе 'paid', сейчас '{deal['status']}'")
    db.update_deal_status(deal_id, STATUS_WAITING_PAYMENT)
    db.add_log("admin_reject", f"deal #{deal_id} reason={reason}", admin_id)
    _notify(deal["seller_id"], f"Оплата по сделке #{deal_id} отклонена админом. Причина: {reason or 'не указана'}")
    _notify(deal["buyer_id"], f"Оплата по сделке #{deal_id} отклонена админом. Причина: {reason or 'не указана'}")
    return db.get_deal(deal_id)


def admin_payout_seller(deal_id: int, admin_id: int) -> Dict[str, Any]:
    """Явная выдача средств продавцу — алиас подтверждения, оставлен для админки."""
    return admin_confirm_payment(deal_id, admin_id)


def cancel_deal(deal_id: int, user_id: int) -> Dict[str, Any]:
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    user = db.get_user(user_id) or {}
    if user_id not in (deal["seller_id"], deal["buyer_id"]) and not user.get("is_admin"):
        raise CoreError("Недостаточно прав")
    if deal["status"] in (STATUS_COMPLETED, STATUS_CANCELLED):
        raise CoreError("Сделка уже закрыта")
    db.update_deal_status(deal_id, STATUS_CANCELLED)
    db.add_log("deal_cancel", f"deal #{deal_id}", user_id)
    _notify(deal["seller_id"], f"Сделка #{deal_id} отменена.")
    _notify(deal["buyer_id"], f"Сделка #{deal_id} отменена.")
    return db.get_deal(deal_id)


# ---------- споры ----------

def open_dispute(deal_id: int, user_id: int, reason: str) -> Dict[str, Any]:
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if user_id not in (deal["seller_id"], deal["buyer_id"]):
        raise CoreError("Открыть спор может только участник сделки")
    if deal["status"] in (STATUS_COMPLETED, STATUS_CANCELLED):
        raise CoreError("Спор по закрытой сделке невозможен")
    if not (reason or "").strip():
        raise CoreError("Укажите причину спора")
    db.create_dispute(deal_id, user_id, reason.strip())
    db.update_deal_status(deal_id, STATUS_DISPUTE)
    db.add_log("dispute_open", f"deal #{deal_id} reason={reason}", user_id)
    _notify(deal["seller_id"], f"По сделке #{deal_id} открыт спор. Причина: {reason}")
    _notify(deal["buyer_id"], f"По сделке #{deal_id} открыт спор. Причина: {reason}")
    for admin in [u for u in db.list_users() if u.get("is_admin")]:
        _notify(admin["id"], f"Открыт спор по сделке #{deal_id}. Решите в админке.")
    return db.get_deal(deal_id)


def resolve_dispute(deal_id: int, admin_id: int, winner: str, resolution: str = "") -> Dict[str, Any]:
    """winner: 'seller' | 'buyer'."""
    _require_admin(admin_id)
    deal = db.get_deal(deal_id)
    if not deal:
        raise CoreError("Сделка не найдена")
    if deal["status"] != STATUS_DISPUTE:
        raise CoreError("Сделка не в споре")
    dispute = db.get_dispute_for_deal(deal_id)
    if not dispute:
        raise CoreError("Спор не найден")
    if winner not in ("seller", "buyer"):
        raise CoreError("winner должен быть 'seller' или 'buyer'")
    if winner == "seller":
        payout = round(deal["amount"] - deal["fee"], 2)
        db.add_balance(deal["seller_id"], payout)
        db.update_deal_status(deal_id, STATUS_COMPLETED)
        msg_text = f"Спор по сделке #{deal_id} решён в пользу продавца. Выплата: {payout:.2f}."
    else:
        db.update_deal_status(deal_id, STATUS_CANCELLED)
        msg_text = f"Спор по сделке #{deal_id} решён в пользу покупателя. Сделка отменена."
    db.resolve_dispute(dispute["id"], "resolved", f"winner={winner}; {resolution}")
    db.add_log("dispute_resolve", f"deal #{deal_id} winner={winner}", admin_id)
    _notify(deal["seller_id"], msg_text)
    _notify(deal["buyer_id"], msg_text)
    return db.get_deal(deal_id)


# ---------- админ ----------

def _require_admin(user_id: int) -> None:
    user = db.get_user(user_id)
    if not user or not user.get("is_admin"):
        raise CoreError("Только админ может выполнить это действие")


def is_admin(user_id: int) -> bool:
    user = db.get_user(user_id)
    return bool(user and user.get("is_admin"))


def grant_admin(user_id: int) -> None:
    db.upsert_user(user_id, None)
    db.set_admin(user_id, True)
    db.add_log("grant_admin", f"user {user_id}")


def list_all_deals() -> List[Dict[str, Any]]:
    return db.list_deals()


def list_all_users() -> List[Dict[str, Any]]:
    return db.list_users()


def list_all_disputes() -> List[Dict[str, Any]]:
    return db.list_disputes()


def list_all_logs(limit: int = 200) -> List[Dict[str, Any]]:
    return db.list_logs(limit)


def bootstrap_admins_from_env() -> None:
    raw = os.environ.get("ADMIN_IDS", "").strip()
    if not raw:
        return
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            grant_admin(int(part))
        except ValueError:
            continue
