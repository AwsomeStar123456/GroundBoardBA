import framebuf
import math
from machine import Pin, I2C  # type: ignore
from lib.xglcd_font import XglcdFont
from lib.ssd1309 import Display

#-----Display Config-----
DISPLAY_WIDTH = 128
DISPLAY_CHAR_WIDTH = 8          # or 8 depending on your font
DISPLAY_ROW_HEIGHT = 8          # or 10/12 if you want more spacing

#-----Display Variables-----
displayI2C = None
displayObject = None
font = None


display_row0 = ""
display_row1 = ""
display_row2 = ""
display_row3 = ""
display_row4 = ""
display_row5 = ""
display_row6 = ""
display_row7 = ""

ByteSunny = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x18\x00\x00\x18\x00 \x00\x04@\x00\x02\x00<\x00\x00f\x00\x00\x81\x00\x80\x81\x01\x98\x00\x19\x98\x00\x19\x80\x81\x01\x00\x81\x00\x00f\x00\x00<\x00@\x00\x02 \x00\x04\x00\x18\x00\x00\x18\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

BytePartlyCloudy = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x01\x00\x04!\x00\x08\x10\x00\x90\x03\x00`\x06\x00 \xf8\x01\x10\x0c\x03\x17\x04\x02 \x02<`\x02`\x10\x03\xc0\x88\x00\x80D\x00\x80@\x00\x80\xc0\x00@\x80\x01`\x00\xff\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

ByteCloudy = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x803\x00\x80@\x00@\xc0\x00@\x80\x0f`\x00\x10x\x00 \x0c\x00 \x04\x00 \x04\x00 \x04\x000\x08\x00\x10\xf8\xff\x0f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

ByteThunderStorm = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x1f\x00\x80!\x00\xc0@\x00@\x80\x07@\x80\x08p\x00\x10\x18\x00 \x04\x00 \x04\x00 \x04\x00 \x040\x10\x088\x18\xf0\x9c\x07\x00\x0c\x00 \x1e\x000\x08\x03\x18\x84\x01\x00\x82\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

ByteSnow = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x0c\x00\x003\x00\x80@\x00@@\x00@\x80\x0f@\x00\x10x\x000\x0c\x08 \x04\x08 \x04k \x04\x1c \x0c\x7f\x108k\x0e\x00\x08\x00\x00\x08\x08\x10\x00\x18\x18\x00\x08\x100\x00\x00\x18\x00\x80\x01\x07\xc0\x01\x03\x00\x00\x00')

ByteRain = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x0c\x00\x003\x00\x80@\x00@@\x00@\x80\x0f@\x00\x10x\x000\x0c\x00 \x04\x00 \x04\x00 \x04\x00 \x0c\x00\x10\xf8\xff\x0f\x00\x00\x00\x00\x00\x00@\x88\x01\x00\x80\x00\x10"\x00\x08 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

ByteHaze = bytearray(b'\x00|\x00\x00\xff\x01\x80\x01\x03\xc0\x00\x06\xe0\x00\x0c|\x00\x0c\x06\x008\x02\x00p\x03\x00\xc0\x03\x00\xc0\x03\x00\xc0\x03\x00\xc0\x06\x00\xc0\xfc\xff\x7f\xf8\xff?\x00\x00\x00\x80\xff\x0f\xc0\xff\x1f\x00\x00\x00\xf8\x7f\x00\xfc\xff\x00\x00\x00\x00\xc0\xff\x03\xe0\xff\x07')

ByteCalm = bytearray(b'\x00\x00\x00\x00\x00\x00\x00~\x00\x80\xff\x01\xe0\x81\x07p\x00\x0e0<\x0c\x18\xff\x18\x98\xc3\x19\x8c\x811\xcc\x003\xcc\x003\xcc\x003\xcc\x003\x8c\x811\x98\xc3\x19\x18\xff\x180<\x0cp\x00\x0e\xe0\x81\x07\x80\xff\x01\x00~\x00\x00\x00\x00\x00\x00\x00')

Arrow = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x18\x00\x00<\x00\x00~\x00\x00\xdb\x00\x80\x99\x01\xc0\x18\x03\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x18\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

# Bitmap overlays (1-bit). Each entry is: key -> (framebuffer, x, y)
_bitmaps_bg = {}
_bitmaps_fg = {}

def startupDisplay():
    global displayI2C, displayObject, font
    displayI2C = I2C(0, freq=400000, scl=Pin(5), sda=Pin(4))  # Pico I2C bus 1
    displayObject = Display(i2c=displayI2C, rst=Pin(2), flip=True)
    font = XglcdFont('font.c', 8, 8)

    if displayI2C is not None and displayObject is not None:
        return True
    else:
        return False
    

def displayCenterText(display, text, row):
    """
    Center text on a specific row using the built-in 8x8 font.
    Compatible with rdagger/micropython-ssd1309 library.
    """
    if display is None:
        return

    text = _sanitize_oled_text(text) if '_sanitize_oled_text' in globals() else text
    text_len = len(text)
    
    # Calculate centered X position
    text_width = text_len * DISPLAY_CHAR_WIDTH
    x = max(0, (DISPLAY_WIDTH - text_width) // 2)
    
    y = row * DISPLAY_ROW_HEIGHT
    
    # Use the internal framebuffer (works on this library)
    display.monoFB.text(text, x, y)
    
def displayRefresh():
    """
    Clear screen, draw background bitmaps, draw all 8 text rows (centered),
    then update the display.
    Compatible with rdagger/micropython-ssd1309.
    """
    global displayObject
    global display_row0, display_row1, display_row2, display_row3
    global display_row4, display_row5, display_row6, display_row7
    global _bitmaps_bg, _bitmaps_fg

    if displayObject is None:
        return

    # Clear the screen
    displayObject.clear()

    # Draw background bitmaps first
    try:
        for _key, (fb, x, y) in _bitmaps_bg.items():
            displayObject.monoFB.blit(fb, x, y)
    except Exception:
        pass

    # Draw all text rows (centered)
    displayCenterText(displayObject, display_row0, 0)
    displayCenterText(displayObject, display_row1, 1)
    displayCenterText(displayObject, display_row2, 2)
    displayCenterText(displayObject, display_row3, 3)
    displayCenterText(displayObject, display_row4, 4)
    displayCenterText(displayObject, display_row5, 5)
    displayCenterText(displayObject, display_row6, 6)
    displayCenterText(displayObject, display_row7, 7)

    # Draw foreground bitmaps on top of everything (optional but recommended)
    try:
        for _key, (fb, x, y) in _bitmaps_fg.items():
            displayObject.monoFB.blit(fb, x, y)
    except Exception:
        pass

    # Important: Update the physical display
    displayObject.present()

def displayClear():
    global displayObject
    global display_row0, display_row1, display_row2, display_row3
    global display_row4, display_row5, display_row6, display_row7

    if displayObject is None:
        return
    
    display_row0 = ""
    display_row1 = ""
    display_row2 = ""
    display_row3 = ""
    display_row4 = ""
    display_row5 = ""
    display_row6 = ""
    display_row7 = ""

    displayObject.clear()
    displayObject.present()

def _sanitize_oled_text(text):
    """Convert Unicode punctuation to ASCII and drop unsupported chars.

    The SSD1306 built-in 8x8 font only reliably supports basic ASCII.
    This prevents smart quotes like ’ from rendering as garbage.
    """
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        return ""

    # Normalize common punctuation to ASCII.
    replacements = {
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201B": "'",  # single high-reversed-9
        "\u2032": "'",  # prime
        "\u201C": '"',  # left double quote
        "\u201D": '"',  # right double quote
        "\u00AB": '"',  # «
        "\u00BB": '"',  # »
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
        "\u2026": "...",  # ellipsis
        "\u00A0": " ",  # non-breaking space
        "\u2009": " ",  # thin space
        "\u200A": " ",
    }

    for k, v in replacements.items():
        if k in s:
            s = s.replace(k, v)

    # Keep display-friendly ASCII. Replace other chars with '?'.
    out = []
    for ch in s:
        o = ord(ch)
        if 32 <= o <= 126:
            out.append(ch)
        elif ch in ("\n", "\r", "\t"):
            out.append(" ")
        else:
            out.append("?")
    return "".join(out)

# ==================== BITMAP HELPERS ====================

def _bitmap_buffer_size(width, height, fmt):
    w = int(width)
    h = int(height)
    if fmt in (framebuf.MONO_HLSB, framebuf.MONO_HMSB):
        return ((w + 7) // 8) * h
    if fmt == framebuf.MONO_VLSB:
        return w * ((h + 7) // 8)
    raise ValueError("unsupported bitmap format")


def _iround(v):
    if v >= 0:
        return int(v + 0.5)
    return int(v - 0.5)


def _rotate_bitmap(src_buf, width, height, fmt, degrees):
    """Rotate a 1-bit bitmap clockwise by `degrees`."""
    if math is None:
        raise RuntimeError("math module not available")

    w = int(width)
    h = int(height)
    deg = float(degrees) % 360.0
    if deg == 0.0:
        return src_buf

    expected = _bitmap_buffer_size(w, h, fmt)
    if len(src_buf) != expected:
        raise ValueError(f"bitmap length mismatch: got {len(src_buf)}, expected {expected}")

    src_fb = framebuf.FrameBuffer(src_buf, w, h, fmt)
    dst_buf = bytearray(expected)
    dst_fb = framebuf.FrameBuffer(dst_buf, w, h, fmt)

    theta = math.radians(deg)
    c = math.cos(theta)
    s = math.sin(theta)

    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0

    for y in range(h):
        y0 = y - cy
        for x in range(w):
            x0 = x - cx
            xs = x0 * c + y0 * s + cx
            ys = -x0 * s + y0 * c + cy

            xi = _iround(xs)
            yi = _iround(ys)
            if 0 <= xi < w and 0 <= yi < h:
                if src_fb.pixel(xi, yi):
                    dst_fb.pixel(x, y, 1)

    return dst_buf


# ==================== PUBLIC BITMAP API ====================

def displaySetBitmap(
    key,
    bitmap_bytes,
    width,
    height,
    x,
    y,
    layer="bg",
    fmt=None,
    rotate_deg=None,
    quantize_deg=None,
):
    """
    Register a 1-bit bitmap to be drawn during displayRefresh().

    Compatible with current ssd1309 + monoFB setup.
    """
    global _bitmaps_bg, _bitmaps_fg

    if fmt is None:
        fmt = framebuf.MONO_HMSB   # or MONO_HLSB — both work well

    if rotate_deg is not None:
        deg = float(rotate_deg)
        if quantize_deg:
            step = float(quantize_deg)
            if step > 0:
                deg = round(deg / step) * step
        bitmap_bytes = _rotate_bitmap(bitmap_bytes, width, height, fmt, deg)

    fb = framebuf.FrameBuffer(bitmap_bytes, width, height, fmt)

    layer = (layer or "bg").lower()
    if layer == "fg":
        _bitmaps_fg[key] = (fb, int(x), int(y))
    else:
        _bitmaps_bg[key] = (fb, int(x), int(y))


def displaySetBitmapRotated(key, bitmap_bytes, width, height, x, y, degrees, layer="bg", quantize_deg=5):
    """Convenience wrapper for rotated bitmaps (clockwise)."""
    return displaySetBitmap(
        key,
        bitmap_bytes,
        width,
        height,
        x,
        y,
        layer=layer,
        fmt=framebuf.MONO_HMSB,
        rotate_deg=degrees,
        quantize_deg=quantize_deg,
    )


def displayRemoveBitmap(key):
    global _bitmaps_bg, _bitmaps_fg
    _bitmaps_bg.pop(key, None)
    _bitmaps_fg.pop(key, None)


def displayClearBitmaps():
    global _bitmaps_bg, _bitmaps_fg
    _bitmaps_bg = {}
    _bitmaps_fg = {}