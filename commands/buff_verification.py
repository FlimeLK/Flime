"""
Перевірка бафів на роботоспроможність.

1) Перевірка узгодженості: кожен effect з каталогу ITEMS має обробник у item_effects.py або play.py.
2) Опційно: «сухий» прогон ItemEffectProcessor для перевірки відсутності винятків.
"""

from typing import Dict, List, Tuple, Optional

# Імпорт каталогу та процесора тільки якщо потрібно
def _get_items():
    try:
        from commands.buff_shop import ITEMS
        return ITEMS
    except Exception as e:
        return {}, str(e)

def _get_processor():
    try:
        from game.item_effects import ItemEffectProcessor
        return ItemEffectProcessor  # успіх - повертаємо клас
    except Exception as e:
        return (None, str(e))  # помилка - кортеж для розрізнення


# Відомі ефекти та де вони обробляються (для звіту та перевірки)
EFFECT_HANDLERS: Dict[str, str] = {
    "reduce_vote": "item_effects.get_vote_reduction, play (голосування)",
    "cancel_night_action": "item_effects.process_blocking_effects / should_block_action(kill)",
    "block_eavesdropping": "item_effects.process_blocking_effects / should_block_action(eavesdrop)",
    "reveal_visitors": "item_effects.process_post_effects(after_night)",
    "extra_role_action": "item_effects.process_protection_effects",
    "block_role_check": "item_effects.process_blocking_effects / should_block_action(check)",
    "check_visitors_on_target": "play: flashlight callback + після ночі",
    "randomize_single_check": "item_effects.should_randomize_single_check, play (перевірка комісара)",
    "invisible_to_night_actions": "item_effects.process_ultra_passive_effects, play (нічні дії)",
    "block_first_visitor_action": "item_effects.process_blocking_effects (block_first_visitor)",
    "escape_voting": "item_effects.can_escape_voting, play (голосування)",
    "randomize_all_checks_and_buffs": "item_effects.process_ultra_passive_effects, play (chaos_mask)",
    "hide_role_and_actions": "item_effects.process_post_effects(after_death)",
    "redirect_action": "item_effects.process_redirect_effects / should_redirect_action",
    "redirect_all_actions_to_random": "item_effects.process_ultra + redirect, play (black_hole)",
    "reflect_all_effects": "item_effects.process_blocking_effects (reflect_effects)",
    "kill_killer_on_death": "item_effects.process_post_effects / should_kill_killer_on_death",
    "reveal_killer": "item_effects.process_post_effects(after_death)",
    "skip_next_night_actions": "item_effects.process_post_effects",
    "skip_next_night_all_actions": "item_effects.process_post_effects",
    "kill_all_attackers": "item_effects.process_post_effects",
    "ignore_block": "item_effects.process_ultra_passive_effects",
    "ignore_first_vote": "item_effects.should_ignore_first_vote",
}

# item_id, які використовуються в play.py, але можуть бути не в ITEMS (адвент/спеціальні)
EXTRA_ITEM_IDS_IN_PLAY: List[str] = ["magnet", "black_hole", "mirror", "candy"]


def verify_buffs() -> Tuple[List[Dict], List[str], Optional[str]]:
    """
    Перевіряє всі бафи з каталогу на наявність обробника ефекту.

    Returns:
        (ok_list, missing_list, error_message)
        - ok_list: список dict з ключами item_id, name, effect, handler_info
        - missing_list: список рядків "item_id (effect): не знайдено обробника"
        - error_message: якщо не вдалося імпортувати ITEMS або ItemEffectProcessor
    """
    items_or_err = _get_items()
    if isinstance(items_or_err, tuple):
        return [], [], f"Помилка імпорту ITEMS: {items_or_err[1]}"
    ITEMS = items_or_err

    ok_list: List[Dict] = []
    missing_list: List[str] = []

    for item_id, item in ITEMS.items():
        name = getattr(item, "name", item_id)
        effect_data = getattr(item, "effect_data", None) or {}
        effect = effect_data.get("effect") if isinstance(effect_data, dict) else None

        if not effect:
            ok_list.append({"item_id": item_id, "name": name, "effect": "(немає effect)", "handler_info": " - "})
            continue

        if effect in EFFECT_HANDLERS:
            ok_list.append({
                "item_id": item_id,
                "name": name,
                "effect": effect,
                "handler_info": EFFECT_HANDLERS[effect],
            })
        else:
            missing_list.append(f"{item_id} ({effect}): не знайдено обробника в EFFECT_HANDLERS")

    return ok_list, missing_list, None


def run_processor_smoke_test(chat_id: int = 0) -> Tuple[bool, Optional[str]]:
    """
    Створює ItemEffectProcessor і викликає основні методи з мінімальними даними.
    Перевіряє відсутність винятків (імпорт, атрибути).

    Returns:
        (success, error_message)
    """
    proc_class_or_err = _get_processor()
    if isinstance(proc_class_or_err, tuple):
        return False, f"Помилка імпорту ItemEffectProcessor: {proc_class_or_err[1]}"
    ItemEffectProcessor = proc_class_or_err

    try:
        proc = ItemEffectProcessor(chat_id)
        # Мінімальні виклики без реального state
        proc.process_ultra_passive_effects(0, None)
        proc.process_blocking_effects(0, None)
        proc.process_redirect_effects(0, None)
        proc.process_protection_effects(0, None)
        proc.process_post_effects(0, None, "after_night")
        proc.process_post_effects(0, None, "after_death")
        proc.should_block_action(0, "kill", None)
        proc.should_block_action(0, "check", None)
        proc.should_redirect_action(0, None)
        proc.get_vote_reduction(0)
        proc.should_randomize_single_check(0)
        proc.can_escape_voting(0)
        proc.should_ignore_first_vote(0)
        proc.should_hide_role_on_death(0)
        proc.should_kill_killer_on_death(0, None)
        proc.should_reveal_checker(0)
        return True, None
    except Exception as e:
        return False, str(e)


def format_verification_report(ok_list: List[Dict], missing_list: List[str], smoke_ok: bool, smoke_err: Optional[str]) -> str:
    """Формує текстовий звіт для відправки в чат."""
    lines = ["🔍 <b>Перевірка бафів</b>\n"]

    if missing_list:
        lines.append("❌ <b>Ефекти без обробника:</b>")
        for m in missing_list:
            lines.append(f"  • {m}")
        lines.append("")
    else:
        lines.append("✅ Всі ефекти з каталогу мають обробник.\n")

    lines.append(f"✅ Перевірено предметів: <b>{len(ok_list)}</b>")
    for x in ok_list:
        lines.append(f"  • {x['item_id']}: {x['effect']} → {x['handler_info']}")
    lines.append("")

    if smoke_ok:
        lines.append("✅ ItemEffectProcessor: smoke test пройдено (без винятків).")
    else:
        lines.append(f"⚠️ ItemEffectProcessor smoke test: помилка - {smoke_err or 'невідома'}")

    return "\n".join(lines)


def run_full_verification(chat_id: int = 0) -> str:
    """Запускає повну перевірку (каталог + smoke test) і повертає звіт."""
    ok_list, missing_list, err = verify_buffs()
    if err:
        return f"❌ Помилка: {err}"

    smoke_ok, smoke_err = run_processor_smoke_test(chat_id)
    return format_verification_report(ok_list, missing_list, smoke_ok, smoke_err)
