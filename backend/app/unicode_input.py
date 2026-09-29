"""Windows Unicode keyboard input, including characters pyautogui drops."""
import ctypes
from ctypes import wintypes


class Keyboard(ctypes.Structure):
    _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class Mouse(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG), ('data', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class Payload(ctypes.Union):
    _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]


class Input(ctypes.Structure):
    _fields_ = [('kind', wintypes.DWORD), ('payload', Payload)]


def type_unicode(text, fail_safe, press_key):
    send = ctypes.windll.user32.SendInput
    send.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    send.restype = wintypes.UINT
    for char in text.replace('\r\n', '\n'):
        fail_safe()
        if char in ('\n', '\t'):
            press_key('enter' if char == '\n' else 'tab')
            continue
        encoded = char.encode('utf-16-le')
        for offset in range(0, len(encoded), 2):
            code = int.from_bytes(encoded[offset:offset + 2], 'little')
            events = (Input * 2)(Input(1, Payload(keyboard=Keyboard(0, code, 4, 0, 0))),
                                 Input(1, Payload(keyboard=Keyboard(0, code, 6, 0, 0))))
            if send(2, events, ctypes.sizeof(Input)) != 2:
                raise OSError('Windows refused keyboard input; check application focus or elevation.')
