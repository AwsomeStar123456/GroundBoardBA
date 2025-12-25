from lib.ssd1306 import SSD1306_I2C
from machine import I2C, Pin

#-----Display Config-----
DISPLAY_I2C_SCL_PIN = 5
DISPLAY_I2C_SDA_PIN = 4
DISPLAY_CONTRAST = 255  # Max contrast
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64
DISPLAY_CHAR_WIDTH = 8  # 8x8 font in ssd1306
DISPLAY_ROW_HEIGHT = 8  # 10 pixels per character row

#-----Display Variables-----
displayI2C = None
displayObject = None

display_row0 = ""
display_row1 = ""
display_row2 = ""
display_row3 = ""
display_row4 = ""
display_row5 = ""
display_row6 = ""
display_row7 = ""

def startupDisplay():
    global displayI2C, displayObject
    
    displayI2C = I2C(0, scl=Pin(DISPLAY_I2C_SCL_PIN), sda=Pin(DISPLAY_I2C_SDA_PIN), freq=400000)
    displayObject = SSD1306_I2C(DISPLAY_WIDTH, DISPLAY_HEIGHT, displayI2C)
    displayObject.contrast(DISPLAY_CONTRAST)

    if displayI2C is not None and displayObject is not None:
        return True

    return False

def displayCenterText(display, text, row):
    # text: string to draw
    # y   : vertical position in pixels
    text_len = len(text)
    text_width = text_len * DISPLAY_CHAR_WIDTH
    x = max(0, (DISPLAY_WIDTH - text_width) // 2)
    display.text(text, x, row*DISPLAY_ROW_HEIGHT)
    display.show()

def displayRefresh():
    global displayObject, display_row0, display_row1, display_row2, display_row3, display_row4, display_row5, display_row6, display_row7
    
    if displayObject is not None:
        displayObject.fill(0)

        displayCenterText(displayObject, display_row0, 0)
        displayCenterText(displayObject, display_row1, 1)
        displayCenterText(displayObject, display_row2, 2)
        displayCenterText(displayObject, display_row3, 3)
        displayCenterText(displayObject, display_row4, 4)
        displayCenterText(displayObject, display_row5, 5)
        displayCenterText(displayObject, display_row6, 6)
        displayCenterText(displayObject, display_row7, 7)

def displayClear():
    global display_row0, display_row1, display_row2, display_row3, display_row4, display_row5, display_row6, display_row7
    
    display_row0 = ""
    display_row1 = ""
    display_row2 = ""
    display_row3 = ""
    display_row4 = ""
    display_row5 = ""
    display_row6 = ""
    display_row7 = ""

    displayRefresh()