import utime
import machine
from utime import sleep
import math
import utils.i2cdisplay as DisplayI2C
import utils.led as LED
import utils.buttons as ButtonPy
import utils.wifi as WiFi
import utils.jsonsupport as supportjson
import updates

time_since_last_metar = 0
metar_data = None

# One heading per LED index. If left as None, we default to evenly-spaced headings
# based on LED.LED_COUNT after LEDs are initialized.
RUNWAY_HEADINGS = None
LED_BRIGHTNESS = None
CROSSWIND_THRESHOLD_KTS = None


def _short(s, max_len=16):
    if s is None:
        return ""
    try:
        s = str(s)
    except Exception:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _display_update_failure(info):
    # Best-effort mapping to short OLED-friendly messages.
    reason = None
    wifi = None
    try:
        if isinstance(info, dict):
            reason = info.get("reason")
            wifi = info.get("wifi")
    except Exception:
        pass

    title = "Update Failed"
    line = None

    wifi_reason = None
    wifi_status = None
    try:
        if isinstance(wifi, dict):
            wifi_reason = wifi.get("reason")
            wifi_status = wifi.get("status")
    except Exception:
        pass

    # Prefer WiFi reason when present.
    if wifi_reason == "password_incorrect":
        line = "Bad Password"
    elif wifi_reason == "no_ssid_found":
        line = "AP Not Found"
    elif wifi_reason == "no_ssid_configured":
        line = "No SSID"
    elif wifi_reason == "connect_failed":
        line = "Connect Failed"
    elif reason == "missing_config":
        missing = info.get("missing") if isinstance(info, dict) else None
        line = "Missing {}".format(missing or "config")
    elif reason == "bad_config":
        line = "Bad Config"
    elif reason == "no_internet":
        line = "No Internet"
    elif reason == "wifi_error":
        line = "WiFi Error"
    elif reason == "no_file_list":
        line = "No File List"
    elif reason == "download_failed":
        line = "DL Failed"
    else:
        line = _short(reason or "failed")

    try:
        DisplayI2C.displayClear()
        DisplayI2C.display_row3 = title
        DisplayI2C.display_row6 = _short(line, 16)
        # If we have a status code, show it too.
        if wifi_status is not None:
            DisplayI2C.display_row7 = _short("ERR Code: {}".format(wifi_status), 16)
        else:
            DisplayI2C.display_row7 = ""
        DisplayI2C.displayRefresh()
    except Exception:
        pass


def leds_set_colors(wind_dir, wind_speed):
    global RUNWAY_HEADINGS, LED_BRIGHTNESS, CROSSWIND_THRESHOLD_KTS

    if LED_BRIGHTNESS is None:
        LED_BRIGHTNESS = 100
    if CROSSWIND_THRESHOLD_KTS is None:
        CROSSWIND_THRESHOLD_KTS = 10

    if RUNWAY_HEADINGS is None:
        RUNWAY_HEADINGS = supportjson.readFromJSON("RUNWAY_HEADINGS")

    wind_dir = int(wind_dir)
    wind_speed = float(wind_speed)    
    runway_headings = RUNWAY_HEADINGS

    if runway_headings is None:
        return

    print(wind_dir, wind_speed)  # Debug: print wind data

    for i, runway_heading in enumerate(runway_headings):
        # Convert to a signed angle in range -180..180 so cos/sin give correct signs.
        diff = (wind_dir - runway_heading) % 360
        if diff > 180:
            diff -= 360

        # Convert to radians for trig functions
        rad = diff * math.pi / 180.0

        # Components: positive headwind component means wind blowing from ahead (good).
        headwind_comp = wind_speed * math.cos(rad)
        crosswind_comp = abs(wind_speed * math.sin(rad))

        # Color rules:
        # - Green: wind <= 3 kts OR headwind component > 0 kts
        # - Yellow: crosswind component > 10 kts
        # - Red: tailwind component > 0
        # - Color = (Green, Red, Blue)
        if wind_speed <= 3:
            color = (255*LED_BRIGHTNESS // 100, 0, 0)
        else:
            color = (0, 0, 255*LED_BRIGHTNESS // 100)

            # Headwind
            if headwind_comp > 0:
                color = (255*LED_BRIGHTNESS // 100, 0, 0)

                # Significant crosswind
                if crosswind_comp > CROSSWIND_THRESHOLD_KTS:
                    color = (255*LED_BRIGHTNESS // 100, 255*LED_BRIGHTNESS // 100, 0)

            # Tailwind
            else:
                color = (0, 255*LED_BRIGHTNESS // 100, 0)
        LED.ledObject[i] = color

    LED.ledObject.write()

def format_unix_utc(ts):
    # ts is seconds since 1970-01-01 (integer)
    tm = utime.gmtime(ts)            # returns (Y,M,D,H,M,S,weekday,yday)
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}Z".format(tm[0], tm[1], tm[2], tm[3], tm[4])


print("Starting Ground Board BA...")

#-----Initialization-----
LED_BRIGHTNESS = supportjson.readFromJSON("LED_BRIGHTNESS")
if LED_BRIGHTNESS is None:
    LED_BRIGHTNESS = 100
print("LED_BRIGHTNESS set to", LED_BRIGHTNESS)

CROSSWIND_THRESHOLD_KTS = supportjson.readFromJSON("CROSSWIND_THRESHOLD_KTS")
if CROSSWIND_THRESHOLD_KTS is None:
    CROSSWIND_THRESHOLD_KTS = 10
print("CROSSWIND_THRESHOLD_KTS set to", CROSSWIND_THRESHOLD_KTS)

#Display Initialization
DisplayI2C.startupDisplay()

DisplayI2C.display_row0 = "Binary Aviation"
DisplayI2C.display_row1 = "METAR Board"
DisplayI2C.display_row3 = "Display"
DisplayI2C.display_row4 = "Initialized"
DisplayI2C.displayRefresh()

#LED Initialization
DisplayI2C.display_row6 = "LEDs"
DisplayI2C.display_row7 = "Initializing"
DisplayI2C.displayRefresh()

LED.startupLED()

DisplayI2C.display_row7 = "Initialized"
DisplayI2C.displayRefresh()

if supportjson.readFromJSON("UPDATE_MODE"):
    DisplayI2C.displayClear()
    print("Update Mode Enabled - Starting updater")
    DisplayI2C.display_row0 = "Update Mode"
    DisplayI2C.display_row1 = "Starting Update"

    DisplayI2C.display_row3 = "Please Do Not"
    DisplayI2C.display_row4 = "Turn Off Power"
    DisplayI2C.displayRefresh()
    sleep(5)
    DisplayI2C.displayClear()

    ok, info = updates.run_update(connect_wifi=True)

    DisplayI2C.displayClear()

    if ok:
        supportjson.writeToJSON("UPDATE_MODE", False)
        DisplayI2C.displayClear()
        DisplayI2C.display_row0 = "Update Mode"
        DisplayI2C.display_row1 = "Success"
        DisplayI2C.display_row3 = "Unit"
        DisplayI2C.display_row4 = "Restarting"
        DisplayI2C.displayRefresh()
        sleep(5)
        machine.reset()
    else:
        supportjson.writeToJSON("UPDATE_MODE", False)
        DisplayI2C.displayClear()
        print("Update failed:", info)
        _display_update_failure(info)
        DisplayI2C.display_row0 = "Update Mode"
        DisplayI2C.display_row1 = "Failed"
        DisplayI2C.display_row3 = "Turn Unit"
        DisplayI2C.display_row4 = "Off/On"
        DisplayI2C.display_row5 = "Wifi Error:"
        DisplayI2C.displayRefresh()
        while True:
            sleep(5)


ButtonPy.startupButtons()
WiFi.startupMetar()
WiFi.resetWifi()

sleep(3)

DisplayI2C.displayClear()
#WiFi.startupWifi()
#print(WiFi.get_metar_raw())
while True:

    # Always define this so we don't NameError when fetch doesn't happen.
    metar_data = None

    if not WiFi.wlan.isconnected():
        DisplayI2C.displayClear()
        wifiStatus = WiFi.startupWifi()
        sleep(5)
        DisplayI2C.displayClear()

    print("Checking internet connectivity...")
    if WiFi.wlan.isconnected():
        print("WiFi connected!")
        internet_ok = WiFi._internet_check_google()
    else:
        print("WiFi not connected!")
        internet_ok = False

    print("Internet connectivity:", internet_ok)
    DisplayI2C.display_row0= "WiFi Status"

    if internet_ok:
        DisplayI2C.display_row1 = "Connected"
        try:
            metar_data = WiFi.get_metar_raw()
        except Exception as e:
            print("METAR fetch failed:", e)
            metar_data = None
        print('METAR data:', metar_data)
    else:
        DisplayI2C.display_row1 = "Disconnected"
    #DisplayI2C.displayRefresh()

    if metar_data and isinstance(metar_data, list):
        metar = metar_data[0]
        wind_speed = metar.get('wspd')
        wind_dir = metar.get('wdir')
        temp = metar.get('temp')
        flight_cat = metar.get('fltCat')
        obstime_time = metar.get('obsTime')

        print("Wind:", wind_dir, "degrees @", wind_speed, "kt")
        print("Temperature:", temp, "°C")
        print("Flight Category:", flight_cat)
        print("METAR Time:", obstime_time)

        leds_set_colors(wind_dir, wind_speed)

        DisplayI2C.display_row3 = "Last Poll Time"
        DisplayI2C.display_row6 = "Metar Observed"
        
        # Zulu / UTC time (after WiFi NTP sync)
        t = utime.gmtime()
        print("{:02d}:{:02d}Z".format(t[3], t[4]))
        DisplayI2C.display_row4 = "{:02d}:{:02d}Z".format(t[3], t[4])

        obsTimeFormatted = format_unix_utc(obstime_time)
        print("Formatted obsTime:", obsTimeFormatted)
        DisplayI2C.display_row7 = obsTimeFormatted
    else:
        print("Unexpected or no METAR format")
        wifiNoConnectReason = wifiStatus["reason"]
        print("WiFi No Connect Reason:", wifiNoConnectReason)

        DisplayI2C.display_row3 = "Failiure Reason"
        if wifiNoConnectReason == "no_ssid_found":
            DisplayI2C.display_row4 = "AP Not Found"
        elif wifiNoConnectReason == "password_incorrect":
            DisplayI2C.display_row4 = "Bad Password"
        else:
            DisplayI2C.display_row4 = "Connection ERR"

        DisplayI2C.display_row6 = "Metar Observed"
        DisplayI2C.display_row7 = "No METAR Data"
        LED.ledObject.fill((0,0,10))
        LED.ledObject.write()

    DisplayI2C.displayRefresh()

    while (ButtonPy.syncButtonPressed == False and time_since_last_metar < 600):
        utime.sleep(1)
        time_since_last_metar += 1
        print ("Time since last metar:", time_since_last_metar)

        if(ButtonPy.apButtonPressed == True):
            LED.ledObject.fill((0,10,10))
            LED.ledObject.write()
            print("AP Button Pressed - Starting AP Mode")
            ButtonPy.consumeApPressed()
            DisplayI2C.displayClear()
            WiFi.startupAccessPointConfigPortal()
            DisplayI2C.displayClear()
            machine.reset()

    time_since_last_metar = 0
    ButtonPy.consumeSyncPressed()