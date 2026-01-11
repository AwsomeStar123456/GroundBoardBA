from machine import Pin
from utime import ticks_ms, ticks_diff
import utils.jsonsupport as supportjson

try:
    import micropython
except Exception:
    micropython = None

syncButtonPressed = False
apButtonPressed = False

BUTTON_PIN_SYNC = None
BUTTON_PIN_AP = None

_DEBOUNCE_MS_DEFAULT = 50
_debounce_ms = _DEBOUNCE_MS_DEFAULT

_sync_button = None
_ap_button = None

_sync_latched = False
_ap_latched = False

_last_irq_sync_ms = 0
_last_irq_ap_ms = 0

_ap_pressed_callback = None


def set_ap_callback(callback):
    """Register a callback to run when the AP button is pressed.

    If MicroPython's scheduler is available, the callback will be invoked via
    micropython.schedule() to keep the IRQ handler fast and safe.

    The callback should accept one positional argument (the scheduled value).
    """
    global _ap_pressed_callback
    _ap_pressed_callback = callback


def _invoke_ap_callback(_arg):
    cb = _ap_pressed_callback
    if cb is None:
        return
    try:
        cb(_arg)
    except Exception as e:
        # Best-effort: don't let callback exceptions destabilize the scheduler.
        print("AP callback error:", e)

def startupButtons():
    global BUTTON_PIN_SYNC, BUTTON_PIN_AP
    global _debounce_ms
    global _sync_button, _ap_button
    global _sync_latched, _ap_latched

    print ("Initializing buttons...")
    
    if BUTTON_PIN_SYNC is None:
        BUTTON_PIN_SYNC = supportjson.readFromJSON("BUTTON_PIN_SYNC")
        print("BUTTON_PIN_SYNC set to", BUTTON_PIN_SYNC)
    if BUTTON_PIN_AP is None:
        BUTTON_PIN_AP = supportjson.readFromJSON("BUTTON_PIN_AP")
        print("BUTTON_PIN_AP set to", BUTTON_PIN_AP)

    debounce_from_config = supportjson.readFromJSON("BUTTON_DEBOUNCE_MS")
    if debounce_from_config is not None:
        _debounce_ms = int(debounce_from_config)
    print("BUTTON_DEBOUNCE_MS set to", _debounce_ms)

    if BUTTON_PIN_SYNC is not None and BUTTON_PIN_AP is not None:
        # Keep references to Pin objects to avoid accidental GC while IRQs are active.
        _sync_button = Pin(BUTTON_PIN_SYNC, Pin.IN, Pin.PULL_UP)
        _ap_button = Pin(BUTTON_PIN_AP, Pin.IN, Pin.PULL_UP)

        _sync_latched = (_sync_button.value() == 0)
        _ap_latched = (_ap_button.value() == 0)

        trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
        _sync_button.irq(trigger=trigger, handler=buttonPressed)
        _ap_button.irq(trigger=trigger, handler=buttonPressed)
    
        print("Buttons initialized.")
    
    print("Buttons complete..")

def buttonPressed(pin):
    # IRQ handler: must be fast and non-blocking. Debounce by time and
    # ensure only one "pressed" event per physical press (latched until release).
    global syncButtonPressed, apButtonPressed
    global _sync_latched, _ap_latched
    global _last_irq_sync_ms, _last_irq_ap_ms

    now = ticks_ms()

    if pin is _sync_button:
        # Always honor release to avoid getting stuck latched if the release IRQ
        # is filtered by debounce (common cause of missed next press).
        if pin.value() != 0:
            _sync_latched = False
            return

        # Debounce presses only.
        if ticks_diff(now, _last_irq_sync_ms) < _debounce_ms:
            return
        _last_irq_sync_ms = now

        # pressed (active-low)
        if not _sync_latched:
            _sync_latched = True
            syncButtonPressed = True
            print("SYNC Button Pressed")
        return

    if pin is _ap_button:
        # Always honor release to avoid getting stuck latched if the release IRQ
        # is filtered by debounce.
        if pin.value() != 0:
            _ap_latched = False
            return

        # Debounce presses only.
        if ticks_diff(now, _last_irq_ap_ms) < _debounce_ms:
            return
        _last_irq_ap_ms = now

        # pressed (active-low)
        if not _ap_latched:
            _ap_latched = True
            if _ap_pressed_callback is not None and micropython is not None:
                try:
                    micropython.schedule(_invoke_ap_callback, 0)
                except Exception as e:
                    # Scheduler queue full or unsupported; fall back to flag.
                    print("AP schedule failed:", e)
                    apButtonPressed = True
            else:
                apButtonPressed = True
            print("AP Button Pressed")
        return


def consumeSyncPressed():
    global syncButtonPressed
    if syncButtonPressed:
        syncButtonPressed = False
        return True
    return False


def consumeApPressed():
    global apButtonPressed
    if apButtonPressed:
        apButtonPressed = False
        return True
    return False
