from machine import Pin
from utime import sleep
import neopixel
import utils.jsonsupport as supportjson

#-----LED Config-----
#LED Pin and Count Stored in .json Config File
LED_PIN = None
LED_COUNT = None

#-----LED Variables-----
ledObject = None

def startupLED():
    global ledObject, LED_PIN, LED_COUNT

    if LED_PIN is None or LED_COUNT is None:
        LED_PIN = supportjson.readFromJSON("LED_PIN")
        LED_COUNT = supportjson.readFromJSON("LED_COUNT")

    ledObject = neopixel.NeoPixel(Pin(LED_PIN), LED_COUNT)

    startupSequenceLED()

def startupSequenceLED():
    global ledObject, LED_COUNT

    if ledObject is not None and LED_COUNT is not None:
        for i in range(LED_COUNT):
            ledObject[i] = (0, 255, 0)  # Red
            ledObject.write()
            sleep(0.3)
            ledObject[i] = (255, 0, 0)  # Green
            ledObject.write()
            sleep(0.3)
            ledObject[i] = (0, 0, 255)  # Blue
            ledObject.write()
            sleep(0.3)
        
        # for i in range(LED_COUNT):
        #     ledObject[i] = (0, 0, 0)  # Off
        #     ledObject.write()
        #     sleep(0.3)
        JSONBRIGHTNESS = supportjson.readFromJSON("LED_BRIGHTNESS")
        if JSONBRIGHTNESS is None:
            JSONBRIGHTNESS = 100

        ledObject.fill((0,0,int(255 * JSONBRIGHTNESS / 100)))
        ledObject.write()
        sleep(1)
        
        #ledObject.fill((0,10,10))
        #ledObject.write()

        # sleep(5)

        # #Test Red
        # ledObject.fill((0,255,0))
        # ledObject.write()
        # sleep(1)

        # #Test Green
        # ledObject.fill((255,0,0))
        # ledObject.write()
        # sleep(1)

        # #Test Blue
        # ledObject.fill((0,0,255))
        # ledObject.write()
        # sleep(1)

        # #Turn Off
        # ledObject.fill((0,0,0))
        # ledObject.write()
        # sleep(1)
        
