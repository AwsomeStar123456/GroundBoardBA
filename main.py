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


def leds_set_colors(wind_dir, wind_speed):
    global RUNWAY_HEADINGS

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
            color = (50, 0, 0)
        else:
            color = (0, 0, 50)

            # Headwind
            if headwind_comp > 0:
                color = (50, 0, 0)

                # Significant crosswind
                if crosswind_comp > 10:
                    color = (50, 50, 0)

            # Tailwind
            else:
                color = (0, 50, 0)

        LED.ledObject[i] = color

    LED.ledObject.write()

def format_unix_utc(ts):
    # ts is seconds since 1970-01-01 (integer)
    tm = utime.gmtime(ts)            # returns (Y,M,D,H,M,S,weekday,yday)
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}Z".format(tm[0], tm[1], tm[2], tm[3], tm[4])


print("Starting Ground Board BA...")

#-----Initialization-----

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
    DisplayI2C.display_row3 = "Update Mode"
    DisplayI2C.display_row4 = "Updating"
    DisplayI2C.displayRefresh()

    ok, info = updates.run_update(connect_wifi=True)
    if ok:
        supportjson.writeToJSON("UPDATE_MODE", False)
        DisplayI2C.display_row6 = "Update"
        DisplayI2C.display_row7 = "Success"
        DisplayI2C.displayRefresh()
        sleep(1)
        machine.reset()
    else:
        print("Update failed:", info)
        DisplayI2C.display_row6 = "Update"
        DisplayI2C.display_row7 = "Failed"
        DisplayI2C.displayRefresh()
        while True:
            sleep(1)


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