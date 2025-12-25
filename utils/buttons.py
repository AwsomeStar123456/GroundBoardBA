from machine import Pin
from utime import ticks_ms, ticks_diff
import utils.jsonsupport as supportjson

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
        if ticks_diff(now, _last_irq_sync_ms) < _debounce_ms:
            return
        _last_irq_sync_ms = now

        if pin.value() == 0:  # pressed (active-low)
            if not _sync_latched:
                _sync_latched = True
                syncButtonPressed = True
                print("SYNC Button Pressed")
        else:  # released
            _sync_latched = False
        return

    if pin is _ap_button:
        if ticks_diff(now, _last_irq_ap_ms) < _debounce_ms:
            return
        _last_irq_ap_ms = now

        if pin.value() == 0:  # pressed (active-low)
            if not _ap_latched:
                _ap_latched = True
                apButtonPressed = True
                print("AP Button Pressed")
        else:  # released
            _ap_latched = False
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
