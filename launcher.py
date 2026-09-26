# -*- coding: utf-8 -*-
"""
Лаунчер бота з консоллю: запуск та зупинка бота в одному вікні з вбудованим виводом логів.
Бот створюється один раз — інакше aiogram дає "Router is already attached" при повторному запуску.
"""
import sys
import os
import queue
import threading
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
except ImportError:
    print("Потрібен Python з tkinter (зазвичай входить у поставку).")
    sys.exit(1)

_bot_loop = None
_bot_instance = None
_bot_stop_future = None
_bot_thread = None
_log_queue_ref = None


def _queue_stdout_stderr(log_queue: queue.Queue):
    class QueueWriter:
        def __init__(self, queue_obj, stream_orig, prefix=""):
            self._queue = queue_obj
            self._orig = stream_orig
            self._prefix = prefix

        def write(self, text):
            if text and text.strip():
                self._queue.put((self._prefix + text,))
            try:
                self._orig.write(text)
                self._orig.flush()
            except Exception:
                pass

        def flush(self):
            try:
                self._orig.flush()
            except Exception:
                pass

    sys.stdout = QueueWriter(log_queue, sys.__stdout__, "")
    sys.stderr = QueueWriter(log_queue, sys.__stderr__, "[stderr] ")


def _schedule_start_safe():
    """Викликати в потоці бота: створити stop_future і запустити polling."""
    global _bot_loop, _bot_stop_future, _bot_instance, _log_queue_ref
    if _bot_loop is None:
        return
    try:
        from run import TelegramBot, TOKEN
        from aiogram import Bot
        if _bot_instance is None:
            _bot_instance = TelegramBot()
            _bot_instance._session_was_closed = False
        bot = _bot_instance
        # При повторному запуску — нова сесія (новий Bot), щоб не було Conflict: only one getUpdates
        if getattr(bot, "_session_was_closed", True):
            bot.bot = Bot(token=TOKEN)
            bot._session_was_closed = False
        _bot_stop_future = _bot_loop.create_future()

        async def run():
            nonlocal bot
            try:
                await bot.setup_bot_commands()
                asyncio.create_task(bot._delivery_loop())
                poll_task = asyncio.create_task(bot.dp.start_polling(bot.bot))
                try:
                    done, pending = await asyncio.wait(
                        [poll_task, _bot_stop_future],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass
                except asyncio.CancelledError:
                    pass
            finally:
                try:
                    if getattr(bot, "bot", None) and getattr(bot.bot, "session", None):
                        await bot.bot.session.close()
                    bot._session_was_closed = True
                except Exception:
                    pass
                if _log_queue_ref:
                    _log_queue_ref.put(("[Бот зупинено]\n",))

        asyncio.ensure_future(run(), loop=_bot_loop)
    except Exception as e:
        if _log_queue_ref:
            import traceback
            _log_queue_ref.put((f"[Помилка бота] {e}\n",))
            _log_queue_ref.put((traceback.format_exc(),))


def _run_bot_in_thread(log_queue: queue.Queue):
    """Запуск або перезапуск polling; бот створюється лише один раз."""
    global _bot_loop, _bot_thread, _log_queue_ref
    _log_queue_ref = log_queue
    try:
        from run import TelegramBot
        from logging import basicConfig, INFO
        basicConfig(level=INFO)
    except Exception as e:
        log_queue.put((f"[Помилка імпорту] {e}\n",))
        return

    def thread_main():
        global _bot_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _bot_loop = loop
        loop.run_forever()

    if _bot_thread is None or not _bot_thread.is_alive():
        _bot_thread = threading.Thread(target=thread_main, daemon=True)
        _bot_thread.start()
        time.sleep(0.5)
    if _bot_loop is None:
        log_queue.put(("[Помилка] Цикл подій ще не готовий. Спробуйте ще раз.\n",))
        return
    _bot_loop.call_soon_threadsafe(_schedule_start_safe)


def _stop_bot():
    global _bot_loop, _bot_stop_future
    if _bot_loop and _bot_stop_future and not _bot_stop_future.done():
        _bot_loop.call_soon_threadsafe(_bot_stop_future.set_result, None)


def main():
    log_queue = queue.Queue()
    _queue_stdout_stderr(log_queue)

    root = tk.Tk()
    root.title("Mafia Bot — Лаунчер")
    root.minsize(600, 400)
    root.geometry("800x500")

    frame_buttons = ttk.Frame(root, padding=5)
    frame_buttons.pack(fill=tk.X)
    bot_running = tk.BooleanVar(value=False)

    def start_bot():
        if bot_running.get():
            return
        bot_running.set(True)
        console.insert(tk.END, "[Запуск бота...]\n")
        console.see(tk.END)
        _run_bot_in_thread(log_queue)

    def stop_bot():
        if not bot_running.get():
            return
        _stop_bot()
        console.insert(tk.END, "[Натиснуто «Зупинити»]\n")
        console.see(tk.END)
        bot_running.set(False)

    ttk.Button(frame_buttons, text="▶ Запустити бота", command=start_bot).pack(side=tk.LEFT, padx=5)
    ttk.Button(frame_buttons, text="■ Зупинити бота", command=stop_bot).pack(side=tk.LEFT, padx=5)
    ttk.Label(frame_buttons, text="Консоль:", font=("", 9)).pack(side=tk.LEFT, padx=(20, 5))

    frame_console = ttk.Frame(root, padding=5)
    frame_console.pack(fill=tk.BOTH, expand=True)
    console = scrolledtext.ScrolledText(
        frame_console,
        wrap=tk.WORD,
        font=("Consolas", 10),
        bg="#1e1e1e",
        fg="#d4d4d4",
        insertbackground="#d4d4d4",
    )
    console.pack(fill=tk.BOTH, expand=True)

    def poll_log_queue():
        try:
            while True:
                msg = log_queue.get_nowait()
                if msg:
                    console.insert(tk.END, msg[0])
                    console.see(tk.END)
        except queue.Empty:
            pass
        root.after(200, poll_log_queue)

    root.after(200, poll_log_queue)
    console.insert(tk.END, "Лаунчер готовий. Натисніть «Запустити бота».\n")
    console.see(tk.END)

    root.protocol("WM_DELETE_WINDOW", lambda: (_stop_bot(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
