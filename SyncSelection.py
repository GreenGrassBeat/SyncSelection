# -*- coding: utf-8 -*-
"""
Notepad++ Python Script
Синхронизация выделения между левой (View 0) и правой (View 1) панелями.
Поддерживает Notepad++ x64 и Python Script 3.0+ (Python 3.14).
Реализована настоящая защита от утечки колбэков при ручных перезапусках скрипта.
"""

from Npp import *
import re
import threading
import time
import ctypes
import sys

# --- НАСТРОЙКИ ---
BIDIRECTIONAL = True
MIN_SELECTION_LENGTH = 2
CASE_SENSITIVE = True

# Искать только слово целиком (исключает частичные совпадения типа section в --bg-section)
WHOLE_WORD_ONLY = True

# Режим отладки.
DEBUG = False
# ------------------

# Определение функций отправки сообщений Windows API
SendMessage = ctypes.windll.user32.SendMessageW
GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState

# Константы сообщений Scintilla API
SCI_SETSEL = 2160                
SCI_VERTICALCENTRECARET = 2619    
SCI_SCROLLCARET = 2169            

# Определение флагов поиска
search_flags = 0 if CASE_SENSITIVE else re.I

# Предохранитель от рекурсии и счетчик уникальных сессий выделения
_is_processing = False
_sync_session_id = 0

def log(message):
    if DEBUG:
        console.write(f"[SyncSelection DEBUG] {message}\n")

def on_select(args):
    global _is_processing, _sync_session_id
    if _is_processing:
        return
        
    updated = args.get('updated', 0) if isinstance(args, dict) else 0
    if not (updated & 2):
        return
        
    if notepad.isSingleView():
        return
        
    hwnd = args.get('hwndFrom')
    
    # Определяем активный редактор и целевой
    if hwnd == editor1.hwnd:
        src_editor = editor1
        dest_editor = editor2
    elif hwnd == editor2.hwnd:
        if not BIDIRECTIONAL:
            return
        src_editor = editor2
        dest_editor = editor1
    else:
        return

    # При каждом изменении выделения создаем новую уникальную сессию
    _sync_session_id += 1
    current_session = _sync_session_id

    try:
        selected_text = src_editor.getSelText()
        
        if selected_text and len(selected_text) >= MIN_SELECTION_LENGTH:
            pattern = re.escape(selected_text)
            
            if WHOLE_WORD_ONLY:
                word_chars = r'[\w-]'
                if re.match(word_chars, selected_text[0]):
                    pattern = r'(?<!' + word_chars + r')' + pattern
                if re.match(word_chars, selected_text[-1]):
                    pattern = pattern + r'(?!' + word_chars + r')'
            
            end_pos = dest_editor.getLength()
            matches = []
            def match_found(m):
                matches.append(m.span(0))
            
            # Поиск первого совпадения
            try:
                dest_editor.research(pattern, match_found, search_flags, 0, end_pos, 1)
            except TypeError:
                dest_editor.research(pattern, match_found, search_flags)
            
            if matches:
                match_start, match_end = matches[0]
                
                # --- БЕЗОПАСНЫЙ ОТЛОЖЕННЫЙ ВЫЗОВ ЧЕРЕЗ DIRECT WIN32 API ---
                def wait_and_apply(session_id):
                    while (GetAsyncKeyState(0x01) & 0x8000) != 0:
                        time.sleep(0.03)
                        if session_id != _sync_session_id:
                            return
                            
                    if session_id != _sync_session_id:
                        return
                        
                    global _is_processing
                    _is_processing = True
                    try:
                        SendMessage(dest_editor.hwnd, SCI_SETSEL, match_start, match_end)
                        SendMessage(dest_editor.hwnd, SCI_VERTICALCENTRECARET, 0, 0)
                        SendMessage(dest_editor.hwnd, SCI_SCROLLCARET, 0, 0)
                    finally:
                        _is_processing = False
                
                threading.Thread(target=wait_and_apply, args=(current_session,)).start()
                
            else:
                # Если совпадение не найдено, сбрасываем выделение во второй панели
                current_pos = dest_editor.getCurrentPos()
                
                def wait_and_clear(session_id):
                    while (GetAsyncKeyState(0x01) & 0x8000) != 0:
                        time.sleep(0.03)
                        if session_id != _sync_session_id:
                            return
                    if session_id != _sync_session_id:
                        return
                        
                    global _is_processing
                    _is_processing = True
                    try:
                        SendMessage(dest_editor.hwnd, SCI_SETSEL, current_pos, current_pos)
                    finally:
                        _is_processing = False
                        
                threading.Thread(target=wait_and_clear, args=(current_session,)).start()
                
    except Exception as e:
        log(f"Ошибка при обработке: {str(e)}")

# Функция инициализации
def init_sync():
    # --- НАСТОЯЩЕЕ РЕШЕНИЕ ПРОБЛЕМЫ УТЕЧКИ КОЛБЭКОВ ---
    # Мы ищем в системном модуле 'sys' ссылку на прошлую зарегистрированную функцию.
    # Если она там есть — мы гарантированно удаляем именно её из Scintilla.
    old_callback = getattr(sys, '_sync_selection_callback', None)
    if old_callback:
        try:
            editor.clearCallbacks(old_callback, [SCINTILLANOTIFICATION.UPDATEUI])
        except Exception:
            pass
            
    # Сохраняем ссылку на текущую функцию в системный модуль для будущего перезапуска
    sys._sync_selection_callback = on_select
    
    # Регистрируем событие через единый прокси-объект `editor`
    editor.callback(on_select, [SCINTILLANOTIFICATION.UPDATEUI])
    console.write("[SyncSelection] Скрипт синхронизации выделения запущен.\n")

if __name__ == '__main__':
    init_sync()