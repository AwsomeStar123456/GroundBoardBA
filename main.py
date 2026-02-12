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

try:
    from utils.version import CURRENT_SW_VERSION, RELEASE_DATE
except Exception:
    CURRENT_SW_VERSION = "9.9.9.9"
    RELEASE_DATE = "ERROR"

time_since_last_metar = 0
metar_data = None

# One heading per LED index. If left as None, we default to evenly-spaced headings
# based on LED.LED_COUNT after LEDs are initialized.
RUNWAY_HEADINGS = None
LED_BRIGHTNESS = None
CROSSWIND_THRESHOLD_KTS = None
METAR_UPDATE_INTERVAL_S = None
DISPLAY_MODE = None


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _parse_wind_dir(wdir):
    """Return (wind_dir_degrees:int|None, is_variable:bool).

    METAR JSON may provide wdir as an int, numeric string, or 'VRB'.
    """
    if wdir is None:
        return None, True

    # Sometimes wdir arrives as a string (e.g. '270', 'VRB').
    try:
        wdir_str = str(wdir).strip().upper()
    except Exception:
        return None, True

    if wdir_str in ("VRB", "VAR"):
        return None, True

    wdir_int = _safe_int(wdir_str)
    if wdir_int is None:
        return None, True

    return wdir_int % 360, False


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

    wind_dir, wind_is_variable = _parse_wind_dir(wind_dir)
    wind_speed = _safe_float(wind_speed)
    runway_headings = RUNWAY_HEADINGS

    if wind_speed is None:
        return

    if runway_headings is None:
        return

    # Variable wind (VRB) has no single direction; show a safe, meaningful pattern.
    # If it is light/variable, treat as calm; otherwise indicate uncertainty.
    if wind_is_variable:
        if wind_speed <= 3:
            LED.ledObject.fill((255 * LED_BRIGHTNESS // 100, 0, 0))
        else:
            LED.ledObject.fill((255 * LED_BRIGHTNESS // 100, 255 * LED_BRIGHTNESS // 100, 0))
        LED.ledObject.write()
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


def metar_ceiling_ft(metar):
    """Return ceiling in feet AGL (int) or None if no ceiling.

    Ceiling is the lowest cloud base with cover BKN/OVC, or vertical visibility (VV).
    This matches aviation usage: FEW/SCT are not ceilings.
    Expects METAR dict similar to AviationWeather.gov JSON (metar.get('clouds') list).
    """
    if not isinstance(metar, dict):
        return None

    clouds = metar.get("clouds")
    if not isinstance(clouds, list) or not clouds:
        return None

    ceiling = None
    for layer in clouds:
        if not isinstance(layer, dict):
            continue
        cover = layer.get("cover")
        base = layer.get("base")
        if cover is None or base is None:
            continue
        try:
            base_ft = int(base)
        except Exception:
            continue

        cover = str(cover).upper()
        if cover in ("BKN", "OVC", "VV"):
            if ceiling is None or base_ft < ceiling:
                ceiling = base_ft

    return ceiling


def metar_condition_str(metar):
    """Return a readable condition string like 'Clear', 'Cloudy', 'Overcast', 'Rain', 'Snow'.

    Priority:
    1) wxString (precip/obstructions) when present
    2) cloud cover summary (OVC/BKN/SCT/FEW/CLR/SKC)
    """
    if not isinstance(metar, dict):
        return "Unknown"

    wx = metar.get("wxString")
    if wx:
        wxu = str(wx).upper()
        # Thunderstorms
        if "TS" in wxu:
            return "Thunder"
        # Frozen precip first
        if "SN" in wxu:
            return "Snow"
        if "PL" in wxu:
            return "Ice Pellets"
        if "FZRA" in wxu or "FZDZ" in wxu:
            return "Freezing"
        # Liquid precip
        if "RA" in wxu:
            return "Rain"
        if "DZ" in wxu:
            return "Drizzle"
        # Obstructions
        if "FG" in wxu:
            return "Fog"
        if "BR" in wxu:
            return "Mist"
        if "HZ" in wxu:
            return "Haze"

    # Cloud-only fallback
    cover = metar.get("cover")
    cover_u = str(cover).upper() if cover is not None else ""

    # Some feeds use CLR/SKC, some omit cover entirely.
    if cover_u in ("CLR", "SKC"):
        return "Clear"

    clouds = metar.get("clouds")
    best = None
    if isinstance(clouds, list):
        # Pick the most significant cover present.
        rank = {"OVC": 4, "BKN": 3, "SCT": 2, "FEW": 1, "CLR": 0, "SKC": 0}
        for layer in clouds:
            if not isinstance(layer, dict):
                continue
            c = layer.get("cover")
            if not c:
                continue
            cu = str(c).upper()
            if cu not in rank:
                continue
            if best is None or rank[cu] > rank.get(best, -1):
                best = cu

    # Prefer computed best cover over top-level cover.
    cover_u = best or cover_u

    if cover_u == "OVC":
        return "Overcast"
    if cover_u == "BKN":
        return "Broken"
    if cover_u == "SCT":
        return "Scattered"
    if cover_u == "FEW":
        return "Few"

    # If we truly have no cloud info, treat as clear-ish.
    if not cover_u:
        return "Clear"

    return "Cloudy"


def APButtonAction():
    print("AP Button Pressed - Starting AP Mode")
    LED.ledObject.fill((0,10,10))
    LED.ledObject.write()
    ButtonPy.consumeApPressed()
    DisplayI2C.displayClear()
    WiFi.startupAccessPointConfigPortal()
    DisplayI2C.displayClear()
    machine.reset()

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

METAR_UPDATE_INTERVAL_S = supportjson.readFromJSON("TIME_SINCE_LAST_METAR_UPDATE_S")
if METAR_UPDATE_INTERVAL_S is None:
    METAR_UPDATE_INTERVAL_S = 600
print("METAR_UPDATE_INTERVAL_S set to", METAR_UPDATE_INTERVAL_S)

DISPLAY_MODE = supportjson.readFromJSON("DISPLAY_MODE")
if DISPLAY_MODE is None:
    DISPLAY_MODE = "Normal"
print("DISPLAY_MODE set to", DISPLAY_MODE)

LED_BRIGHTNESS = supportjson.readFromJSON("LED_BRIGHTNESS")
if LED_BRIGHTNESS is None:
    LED_BRIGHTNESS = 100
print("LED_BRIGHTNESS set to", LED_BRIGHTNESS)

#Display Initialization
DisplayI2C.startupDisplay()

DisplayI2C.display_row0 = "Binary Aviation"
DisplayI2C.display_row1 = "RunwaySense"
DisplayI2C.display_row3 = "Display"
DisplayI2C.display_row4 = "Initialized"
DisplayI2C.displayRefresh()

#LED Initialization
DisplayI2C.display_row6 = "LEDs"
DisplayI2C.display_row7 = "Initializing"
DisplayI2C.displayRefresh()

LED.startupLED()

ButtonPy.startupButtons()

# Route AP button presses directly to the main handler (scheduled out of IRQ).
try:
    ButtonPy.set_ap_callback(lambda _arg: APButtonAction())
except Exception as e:
    print("Failed to register AP callback:", e)

DisplayI2C.display_row7 = "Initialized"
DisplayI2C.displayRefresh()

LED.ledObject.fill((int(255 * LED_BRIGHTNESS / 100),int(255 * LED_BRIGHTNESS / 100),int(255 * LED_BRIGHTNESS / 100)))
LED.ledObject.write()
sleep(1)


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
        DisplayI2C.display_row5 = "Error:"
        DisplayI2C.displayRefresh()
        while True:
            sleep(5)

DisplayI2C.displayClear()
DisplayI2C.display_row0 = "Binary Aviation"
DisplayI2C.display_row1 = "RunwaySense"

DisplayI2C.display_row3 = "Software Version"
DisplayI2C.display_row4 = CURRENT_SW_VERSION

DisplayI2C.display_row6 = "Date of Release"
DisplayI2C.display_row7 = RELEASE_DATE
DisplayI2C.displayRefresh()
sleep(10)
DisplayI2C.displayClear()

WiFi.startupMetar()
WiFi.resetWifi()

sleep(3)

DisplayI2C.displayClear()
#WiFi.startupWifi()
#print(WiFi.get_metar_raw())
while True:

    metar_data = None
    DisplayI2C.displayClear()

    wifiStatus = {"reason": None, "status": None}
    try:

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

        if internet_ok == False:
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

            if metar_data is None:
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
            wind_gust = metar.get('wgst')
            wind_dir = metar.get('wdir')
            temp = metar.get('temp')
            flight_cat = metar.get('fltCat')
            obstime_time = metar.get('obsTime')

            wind_dir_deg, wind_is_variable = _parse_wind_dir(wind_dir)

            if wind_is_variable:
                print("Wind: VRB @", wind_speed, "kt")
            else:
                print("Wind:", wind_dir_deg, "degrees @", wind_speed, "kt")
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
            wifiNoConnectReason = None
            try:
                wifiNoConnectReason = wifiStatus.get("reason") if isinstance(wifiStatus, dict) else None
            except Exception:
                wifiNoConnectReason = None
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


        if(DISPLAY_MODE == "Normal" and metar_data and isinstance(metar_data, list)):
            metarCondition = metar_condition_str(metar)

            
            DisplayI2C.displayClear()
            #DisplayI2C.displaySetBitmap("arrow", Arrow, 24, 24, 10, 18, layer="bg")
            DisplayI2C.display_row0 = "     " + metar_condition_str(metar)

            ceiling_ft = metar_ceiling_ft(metar)
            if ceiling_ft is None:
                DisplayI2C.display_row1 = "     "
            else:
                DisplayI2C.display_row1 = "     " + str(ceiling_ft) + " ft"

            
            icon = None
            if metarCondition == "Clear":
                icon = DisplayI2C.ByteSunny
            elif metarCondition in ("Few", "Scattered"):
                icon = DisplayI2C.BytePartlyCloudy
            elif metarCondition in ("Broken", "Overcast"):
                icon = DisplayI2C.ByteCloudy
            elif metarCondition == "Thunder":
                icon = DisplayI2C.ByteThunderStorm
            elif metarCondition in ("Snow", "Ice Pellets", "Freezing"):
                icon = DisplayI2C.ByteSnow
            elif metarCondition in ("Rain", "Drizzle"):
                icon = DisplayI2C.ByteRain
            elif metarCondition in ("Fog", "Mist", "Haze"):
                icon = DisplayI2C.ByteHaze
            if icon is not None:
                DisplayI2C.displaySetBitmap("clear", icon, 24, 24, 10, 0, layer="bg")

                    

            wind_speed_num = _safe_float(wind_speed) or 0.0
            wind_dir_deg, wind_is_variable = _parse_wind_dir(wind_dir)

            if wind_speed_num == 0:
                DisplayI2C.displaySetBitmap("arrow", DisplayI2C.ByteCalm, 24, 24, 10, 24, layer="bg", quantize_deg=5)
                DisplayI2C.display_row3 = "     0 @ 0 kt"
            elif wind_is_variable or wind_dir_deg is None:
                DisplayI2C.displaySetBitmap("arrow", DisplayI2C.ByteCalm, 24, 24, 10, 24, layer="bg", quantize_deg=5)
                DisplayI2C.display_row3 = "     VRB @ " + str(wind_speed) + " kt"
            else:
                # METAR wind_dir is the direction the wind is FROM.
                # For a "wind is going" arrow, flip 180 degrees.
                arrow_dir = (int(wind_dir_deg) + 180) % 360
                DisplayI2C.displaySetBitmapRotated("arrow", DisplayI2C.Arrow, 24, 24, 10, 24, arrow_dir, layer="bg", quantize_deg=5)
                DisplayI2C.display_row3 = "     " + str(wind_dir_deg) + " @ " + str(wind_speed) + " kt"

            if wind_speed_num == 0:
                DisplayI2C.display_row4 = "     Wind Calm"
            elif(wind_gust is None):
                DisplayI2C.display_row4 = ""
            else:
                DisplayI2C.display_row4 = "     Gust " + str(wind_gust) + " kt"

            DisplayI2C.display_row6 = "Metar Observed"
            DisplayI2C.display_row7 = obsTimeFormatted
            DisplayI2C.displayRefresh()
            sleep(5)

        DisplayI2C.displayRefresh()
    except Exception as e:
        print("Main loop exception:", e)
        DisplayI2C.displayClear()
        DisplayI2C.display_row3 = "Major Error"
        DisplayI2C.displayRefresh()
        LED.ledObject.fill((0,255,0))
        LED.ledObject.write()
    
    # If we failed to fetch METAR data, retry quickly.
    # Otherwise, respect the configured update interval.
    poll_interval_s = METAR_UPDATE_INTERVAL_S

    if metar_data is None:
        poll_interval_s = 7

    print("Next METAR fetch in", poll_interval_s, "seconds")

    while ((ButtonPy.syncButtonPressed == False) and (time_since_last_metar < poll_interval_s)):
        utime.sleep(1)
        time_since_last_metar += 1
        print ("Time since last metar:", time_since_last_metar)

    time_since_last_metar = 0
    ButtonPy.consumeSyncPressed()