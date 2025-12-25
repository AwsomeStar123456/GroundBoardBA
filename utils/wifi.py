import utils.jsonsupport as supportjson
from utime import sleep
import network
import utils.i2cdisplay as DisplayI2C
import gc
import socket
import ssl
import utime
import json

try:
    import machine
except Exception:
    machine = None

try:
    import ntptime
except Exception:
    ntptime = None


#-----Wifi Config-----
WIFI_SSID = None
WIFI_PASSWORD = None
MAX_WIFI_WAIT = None

#-----Wifi Variables-----
wlan = network.WLAN(network.STA_IF)


# ----- AP Mode Config Portal -----
WIFI_AP_SSID = None
WIFI_AP_PASSWORD = None
WIFI_WAIT_AFTER_SUBMIT_S = None
ap_server_socket = None


WIFI_HTML_FORM_TEMPLATE = """\
HTTP/1.1 200 OK
Content-Type: text/html
Connection: close

<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\">
  <title>Ground Board Wi-Fi Setup</title>
  <style>
    body { font-family: sans-serif; max-width: 420px; margin: 20px auto; }
    label { display: block; margin-top: 12px; }
    input[type=text], input[type=password], input[type=number] { width: 100%; padding: 8px; }
    input[type=submit] { margin-top: 16px; padding: 10px 16px; }
  </style>
</head>
<body>
  <h2>Binary Aviation Ground Board</h2>
  <p>Enter Wi-Fi credentials and submit:</p>
  <form method=\"POST\">
    <label>WiFi SSID:
      <input type=\"text\" name=\"ssid\">
    </label>
    <label>WiFi Password:
      <input type=\"password\" name=\"password\">
    </label>
        <label>LED Brightness (%):
            <input type=\"number\" name=\"led_brightness\" min=\"0\" max=\"100\" step=\"1\" value=\"__LED_BRIGHTNESS__\">
        </label>
        <label>Crosswind Threshold (kts 0-100):
            <input type=\"number\" name=\"crosswind_threshold\" min=\"0\" max=\"100\" step=\"1\" value=\"__CROSSWIND_THRESHOLD__\">
        </label>
        <input type=\"submit\" name=\"action\" value=\"Save\">
        <input type=\"submit\" name=\"action\" value=\"Update\">
  </form>
</body>
</html>
"""


WIFI_HTML_OK = """\
HTTP/1.1 200 OK
Content-Type: text/html
Connection: close

<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\">
  <title>Saved</title>
</head>
<body>
  <h2>Saved</h2>
  <p>Wi-Fi settings were saved to config.json.</p>
  <p>You can now disconnect from this Wi-Fi network.</p>
</body>
</html>
"""


WIFI_HTML_UPDATE = """\
HTTP/1.1 200 OK
Content-Type: text/html
Connection: close

<!DOCTYPE html>
<html>
<head>
    <meta charset=\"utf-8\">
    <title>Updating</title>
</head>
<body>
    <h2>Update Mode Enabled</h2>
    <p>UPDATE_MODE was set to true in config.json.</p>
    <p>Rebooting now...</p>
</body>
</html>
"""


def _ap_url_decode(s):
    # Minimal application/x-www-form-urlencoded decode
    if s is None:
        return ""
    s = s.replace('+', ' ')
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '%' and i + 2 < len(s):
            try:
                out.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except Exception:
                pass
        out.append(ch)
        i += 1
    return ''.join(out)


def _ap_parse_post_body(body):
    params = {}
    if not body:
        return params
    parts = body.split('&')
    for p in parts:
        if '=' in p:
            k, v = p.split('=', 1)
        else:
            k, v = p, ''
        params[_ap_url_decode(k)] = _ap_url_decode(v)
    return params


def _ap_read_http_request(cl, timeout_s=3, max_bytes=4096):
    try:
        cl.settimeout(timeout_s)
    except Exception:
        pass

    data = b""
    try:
        while len(data) < max_bytes:
            chunk = cl.recv(512)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                # headers received; body may already be included
                # If Content-Length exists and body incomplete, keep reading.
                try:
                    header, body = data.split(b"\r\n\r\n", 1)
                    header_text = header.decode('latin-1')
                    clen = 0
                    for line in header_text.split('\r\n'):
                        if line.lower().startswith('content-length:'):
                            clen = int(line.split(':', 1)[1].strip())
                            break
                    if clen and len(body) < clen:
                        continue
                except Exception:
                    pass
                break
    except Exception:
        return None

    return data if data else None


def _ap_send(cl, payload):
    try:
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        cl.send(payload)
    except Exception:
        try:
            cl.write(payload)
        except Exception:
            pass


def _save_wifi_config(ssid, password):
    # Only overwrite if user actually provided a value.
    if ssid is not None and ssid != "":
        supportjson.writeToJSON("WIFI_SSID", ssid)
    # Allow empty password for open networks.
    if password is not None:
        supportjson.writeToJSON("WIFI_PASSWORD", password)


def _parse_int_in_range(value, min_value=0, max_value=100):
    if value is None:
        return None
    try:
        s = str(value).strip()
        if s == "":
            return None
        n = int(float(s))
    except Exception:
        return None

    if n < min_value:
        n = min_value
    if n > max_value:
        n = max_value
    return n


def _save_board_config(led_brightness, crosswind_threshold):
    led = _parse_int_in_range(led_brightness, 0, 100)
    if led is not None:
        supportjson.writeToJSON("LED_BRIGHTNESS", led)

    cross = _parse_int_in_range(crosswind_threshold, 0, 100)
    if cross is not None:
        supportjson.writeToJSON("CROSSWIND_THRESHOLD_KTS", cross)


def _render_wifi_form():
    led = supportjson.readFromJSON("LED_BRIGHTNESS")
    cross = supportjson.readFromJSON("CROSSWIND_THRESHOLD_KTS")

    led_s = "" if led is None else str(led)
    cross_s = "" if cross is None else str(cross)

    html = WIFI_HTML_FORM_TEMPLATE
    html = html.replace("__LED_BRIGHTNESS__", led_s)
    html = html.replace("__CROSSWIND_THRESHOLD__", cross_s)
    return html


def _set_update_mode_and_reset():
    supportjson.writeToJSON("UPDATE_MODE", True)
    # Give the response a moment to flush before rebooting.
    _sleep_ms(500)
    if machine is not None:
        try:
            machine.reset()
        except Exception:
            pass


def startupAccessPointConfigPortal():
    """Start AP mode and host a simple web page to configure WiFi settings.

    - Connect phone to AP SSID/password.
    - Browse to http://192.168.4.1
    - Submit SSID/password/max wait.
    """
    global wlan, ap_server_socket
    global WIFI_AP_SSID, WIFI_AP_PASSWORD, WIFI_WAIT_AFTER_SUBMIT_S

    if WIFI_AP_SSID is None:
        WIFI_AP_SSID = supportjson.readFromJSON("WIFI_AP_SSID")
    if not WIFI_AP_SSID:
        WIFI_AP_SSID = "GroundBoardBA-Setup"

    if WIFI_AP_PASSWORD is None:
        WIFI_AP_PASSWORD = supportjson.readFromJSON("WIFI_AP_PASSWORD")
    if not WIFI_AP_PASSWORD:
        WIFI_AP_PASSWORD = "configureme"  # >=8 chars for WPA2

    if WIFI_WAIT_AFTER_SUBMIT_S is None:
        w = supportjson.readFromJSON("WIFI_WAIT_AFTER_SUBMIT_S")
        WIFI_WAIT_AFTER_SUBMIT_S = int(w) if w is not None else 2

    # OLED instructions
    try:
        DisplayI2C.displayClear()
        DisplayI2C.display_row0 = "WiFi AP Mode"
        DisplayI2C.display_row2 = "SSID"
        DisplayI2C.display_row3 = WIFI_AP_SSID
        DisplayI2C.display_row4 = "PASSWORD"
        DisplayI2C.display_row5 = WIFI_AP_PASSWORD
        DisplayI2C.display_row6 = "Open Browser To:"
        DisplayI2C.display_row7 = "192.168.4.1"
        DisplayI2C.displayRefresh()
    except Exception:
        pass

    # Best-effort: stop STA while running AP mode.
    try:
        if wlan is not None:
            try:
                wlan.disconnect()
            except Exception:
                pass
            try:
                wlan.active(False)
            except Exception:
                pass
    except Exception:
        pass
    _sleep_ms(150)

    # Close old server socket if any
    try:
        if ap_server_socket is not None:
            ap_server_socket.close()
    except Exception:
        pass
    ap_server_socket = None

    ap = network.WLAN(network.AP_IF)
    try:
        ap.active(False)
    except Exception:
        pass
    _sleep_ms(150)

    try:
        ap.config(essid=WIFI_AP_SSID, password=WIFI_AP_PASSWORD)
    except Exception:
        # If password rejected by firmware, fall back to open AP
        ap.config(essid=WIFI_AP_SSID)

    ap.active(True)
    while not ap.active():
        _sleep_ms(100)

    print("Access Point started.")
    print("  SSID:    ", WIFI_AP_SSID)
    print("  Password:", WIFI_AP_PASSWORD)
    print("Open: http://192.168.4.1")
    try:
        print("AP IP:", ap.ifconfig()[0])
    except Exception:
        pass

    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    ap_server_socket = s
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass

    s.bind(addr)
    s.listen(1)
    print("Listening on", addr)

    try:
        while True:
            cl = None
            try:
                cl, remote_addr = s.accept()
                raw = _ap_read_http_request(cl)
                if not raw:
                    try:
                        cl.close()
                    except Exception:
                        pass
                    continue

                try:
                    req_str = raw.decode('utf-8')
                except Exception:
                    req_str = raw.decode('latin-1')

                first_line_end = req_str.find('\r\n')
                if first_line_end == -1:
                    _ap_send(cl, _render_wifi_form())
                    cl.close()
                    continue

                first_line = req_str[:first_line_end]
                method = first_line.split(' ')[0]

                if "\r\n\r\n" in req_str:
                    headers, body = req_str.split("\r\n\r\n", 1)
                else:
                    headers, body = req_str, ""

                if method == "POST":
                    params = _ap_parse_post_body(body)
                    ssid = params.get("ssid", "")
                    password = params.get("password", "")
                    led_brightness = params.get("led_brightness", "")
                    crosswind_threshold = params.get("crosswind_threshold", "")
                    action = params.get("action", "Save")

                    print("\n=== WiFi settings received ===")
                    print("SSID:     '{}'".format(ssid))
                    print("Password: '{}'".format(password))
                    print("==============================\n")

                    # Save to config.json
                    if action == "Update":
                        # Optionally persist SSID/password if provided along with Update.
                        _save_wifi_config(ssid, password)
                        _save_board_config(led_brightness, crosswind_threshold)
                        _ap_send(cl, WIFI_HTML_UPDATE)
                        try:
                            cl.close()
                        except Exception:
                            pass
                        # Set flag and reboot.
                        _set_update_mode_and_reset()
                        break
                    else:
                        _save_wifi_config(ssid, password)
                        _save_board_config(led_brightness, crosswind_threshold)
                        _ap_send(cl, WIFI_HTML_OK)
                        try:
                            cl.close()
                        except Exception:
                            pass
                        break
                else:
                    _ap_send(cl, _render_wifi_form())
                    try:
                        cl.close()
                    except Exception:
                        pass

            except Exception as e:
                print("Error handling AP client:", e)
                try:
                    if cl is not None:
                        cl.close()
                except Exception:
                    pass

    finally:
        try:
            s.close()
        except Exception:
            pass
        ap_server_socket = None

        print("Waiting {}s then shutting down AP...".format(WIFI_WAIT_AFTER_SUBMIT_S))
        sleep(WIFI_WAIT_AFTER_SUBMIT_S)
        try:
            ap.active(False)
        except Exception:
            pass

        print("Access Point stopped.")

        # Re-init STA interface object for normal operation.
        try:
            wlan = network.WLAN(network.STA_IF)
        except Exception:
            pass


# ----- Time Sync (NTP) -----
NTP_HOST = None
NTP_RETRIES = None
_time_synced = False


def resetWifi():
    """Disconnect from any WiFi network and reset WLAN state.

    This is intended to put the device back into a known-clean state so a
    subsequent call to startupWifi() behaves like a fresh boot.
    """
    global wlan
    global _time_synced

    print("WiFi reset: disconnect + disable interface")
    _time_synced = False

    try:
        if wlan is not None:
            try:
                wlan.disconnect()
            except Exception:
                pass
            try:
                wlan.active(False)
            except Exception:
                pass
    except Exception:
        pass

    sleep(0.25)

    # Recreate WLAN object (some firmware behaves better after re-init)
    try:
        wlan = network.WLAN(network.STA_IF)
    except Exception:
        wlan = None

    # Leave interface off by default; caller can call startupWifi() to enable/connect.
    try:
        if wlan is not None:
            wlan.active(False)
    except Exception:
        pass

    print("WiFi reset: complete")


def sync_time_ntp(force=False):
    """Sync device RTC to UTC using NTP.

    Returns True on success, False otherwise.
    """
    global NTP_HOST, NTP_RETRIES, _time_synced

    if _time_synced and not force:
        return True

    if ntptime is None:
        print("NTP sync skipped: ntptime not available")
        return False

    if NTP_HOST is None:
        NTP_HOST = supportjson.readFromJSON("NTP_HOST")
    if not NTP_HOST:
        NTP_HOST = "pool.ntp.org"

    if NTP_RETRIES is None:
        r = supportjson.readFromJSON("NTP_RETRIES")
        NTP_RETRIES = int(r) if r is not None else 3

    try:
        ntptime.host = NTP_HOST
    except Exception:
        pass

    for attempt in range(1, NTP_RETRIES + 1):
        try:
            print("NTP sync attempt", attempt, "host=", NTP_HOST)
            ntptime.settime()  # sets RTC to UTC
            _time_synced = True
            now = utime.gmtime()
            print("NTP synced UTC:", "{:02d}:{:02d}:{:02d}Z".format(now[3], now[4], now[5]))
            return True
        except Exception as e:
            print("NTP sync failed:", e)
            _sleep_ms(300)

    return False


# ----- METAR Config (aviationweather.gov / NOAA) -----
# NOTE: This endpoint is hosted at aviationweather.gov and provides METAR data.
METAR_HOST = "aviationweather.gov"
METAR_PORT = 443

METAR_STATION_ID = None  # e.g. "KSLC" or "KSLC,KBTF"
METAR_SOCKET_TIMEOUT_S = 10
METAR_FETCH_RETRIES = 3


def startupMetar():
    """Load METAR settings from config.json."""
    global METAR_STATION_ID, METAR_SOCKET_TIMEOUT_S, METAR_FETCH_RETRIES

    if METAR_STATION_ID is None:
        METAR_STATION_ID = supportjson.readFromJSON("METAR_STATION_ID")

    print(
        "METAR Config - Stations:",
        METAR_STATION_ID,
    )


def _sleep_ms(ms):
    try:
        utime.sleep_ms(ms)
    except Exception:
        utime.sleep(ms / 1000.0)


def _wrap_tls(sock, host):
    """Wrap a socket for TLS in a way that works across firmware."""
    try:
        return ssl.wrap_socket(sock, server_hostname=host)
    except Exception:
        return ssl.wrap_socket(sock)


def _format_station_ids(station_ids):
    if station_ids is None:
        return None
    if isinstance(station_ids, (list, tuple)):
        return ",".join(station_ids)
    return str(station_ids)


def get_metar_raw(station_ids=None):
    """Fetch METAR JSON via raw TLS socket.

    Retries on transient timeouts (often reported as -110 in MicroPython).
    Uses list+join buffering to reduce heap fragmentation.

    Returns parsed JSON (usually a list of dicts) or None on failure.
    """
    global METAR_STATION_ID, METAR_SOCKET_TIMEOUT_S, METAR_FETCH_RETRIES

    if METAR_STATION_ID is None or METAR_SOCKET_TIMEOUT_S is None or METAR_FETCH_RETRIES is None:
        startupMetar()

    # Time sync from internet (Zulu/UTC) – do once.
    # We only try when WiFi is connected and internet appears reachable.
    try:
        if wlan is not None and wlan.isconnected() and not _time_synced:
            if _internet_check_google():
                sync_time_ntp()
    except Exception:
        pass

    ids = _format_station_ids(station_ids) or METAR_STATION_ID
    timeout_s = METAR_SOCKET_TIMEOUT_S if METAR_SOCKET_TIMEOUT_S is not None else 8
    retries = METAR_FETCH_RETRIES if METAR_FETCH_RETRIES is not None else 3

    path = "/api/data/metar?ids={}&format=json".format(ids)

    for attempt in range(1, retries + 1):
        s = None
        ss = None
        try:
            gc.collect()

            addr = socket.getaddrinfo(METAR_HOST, METAR_PORT)[0][-1]
            print("Resolved", METAR_HOST, "to", addr, "(attempt", attempt, "of", retries, ")")

            s = socket.socket()
            try:
                s.settimeout(timeout_s)
            except Exception:
                pass
            s.connect(addr)

            ss = _wrap_tls(s, METAR_HOST)
            # Some MicroPython SSL sockets don't expose settimeout().
            try:
                settimeout = getattr(ss, "settimeout", None)
                if settimeout:
                    settimeout(timeout_s)
            except Exception:
                pass

            # HTTP/1.0 avoids chunked transfer encoding complexity.
            req = (
                "GET {} HTTP/1.0\r\n"
                "Host: {}\r\n"
                "User-Agent: GroundBoardBA\r\n"
                "Accept: application/json\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).format(path, METAR_HOST)

            try:
                ss.write(req.encode())
            except Exception:
                ss.send(req.encode())

            chunks = []
            while True:
                try:
                    chunk = ss.read(1024)
                except Exception:
                    chunk = ss.recv(1024)
                if not chunk:
                    break
                chunks.append(chunk)

            response = b"".join(chunks)
            header_end = response.find(b"\r\n\r\n")
            if header_end == -1:
                print("get_metar_raw: Header/Body split failed")
                return None

            header_bytes = response[:header_end]
            body_bytes = response[header_end + 4 :]
            status_line = header_bytes.split(b"\r\n", 1)[0]

            status_code = None
            try:
                status_code = int(status_line.split(b" ")[1])
            except Exception:
                pass

            if status_code != 200:
                print("get_metar_raw: HTTP status", status_code)
                return None

            if not body_bytes:
                print("get_metar_raw: Empty body")
                return None

            try:
                body_text = body_bytes.decode("utf-8")
            except Exception:
                body_text = body_bytes.decode("latin-1")

            return json.loads(body_text)

        except OSError as e:
            # Common transient timeout in MicroPython is ETIMEDOUT (110) reported as -110.
            err = e.args[0] if getattr(e, "args", None) else e
            if err in (-110, 110):
                print("get_metar_raw timeout:", err)
                _sleep_ms(200)
                continue
            print("get_metar_raw failed:", e)
            return None

        except Exception as e:
            print("get_metar_raw failed:", e)
            return None

        finally:
            try:
                if ss:
                    ss.close()
            except Exception:
                pass
            try:
                if s:
                    s.close()
            except Exception:
                pass

    return None


def _decode_ssid(raw_ssid):
    try:
        return raw_ssid.decode() if isinstance(raw_ssid, (bytes, bytearray)) else str(raw_ssid)
    except Exception:
        return str(raw_ssid)


def _ssid_in_scan(nets, target_ssid):
    if not target_ssid or not nets:
        return False
    for net in nets:
        try:
            ssid = _decode_ssid(net[0])
            if ssid == target_ssid:
                return True
        except Exception:
            pass
    return False


def _wlan_status_name(status_code):
    # Common MicroPython/Pico W WLAN status codes.
    if status_code == -3:
        return "WRONG_PASSWORD"
    if status_code == -2:
        return "NO_AP_FOUND"
    if status_code == -1:
        return "CONNECT_FAIL"
    if status_code == 0:
        return "IDLE"
    if status_code == 1:
        return "CONNECTING"
    if status_code == 2:
        return "GOT_IP?"
    if status_code == 3:
        return "GOT_IP"
    return str(status_code)


def _internet_check_google(timeout_s=3):
    """Ping-like internet check using Google generate_204 over HTTP.

    ICMP ping isn't consistently available in MicroPython, so we treat:
    - DNS resolve + TCP connect + HTTP response as "internet working".
    """
    host = "clients3.google.com"
    port = 80

    try:
        addr = socket.getaddrinfo(host, port)[0][-1]
    except Exception as e:
        print("Internet check: DNS failed:", e)
        return False

    s = None
    try:
        s = socket.socket()
        try:
            s.settimeout(timeout_s)
        except Exception:
            pass

        s.connect(addr)
        req = "GET /generate_204 HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n".format(host)
        s.send(req.encode())
        data = s.recv(64)
        if not data:
            return False
        # Typical response: HTTP/1.1 204 No Content
        return data.startswith(b"HTTP/")
    except Exception as e:
        print("Internet check failed:", e)
        return False
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass

def startupWifi():
    global WIFI_SSID, WIFI_PASSWORD, MAX_WIFI_WAIT, wlan

    #Initalize Wifi Variables from JSON Config if not already set
    if( WIFI_SSID is None):
        WIFI_SSID = supportjson.readFromJSON("WIFI_SSID")
    if( WIFI_PASSWORD is None):
        WIFI_PASSWORD = supportjson.readFromJSON("WIFI_PASSWORD")
    if( MAX_WIFI_WAIT is None):
        MAX_WIFI_WAIT = supportjson.readFromJSON("MAX_WIFI_WAIT")

    print("WiFi Config - SSID:", WIFI_SSID, "Password:", WIFI_PASSWORD, "Max Wait:", MAX_WIFI_WAIT)
    
    #Setup display for WiFi Connection Status
    DisplayI2C.displayClear()
    DisplayI2C.display_row0 = "WiFi"
    DisplayI2C.display_row1 = "Connecting"
    DisplayI2C.display_row3 = "SSID"
    DisplayI2C.display_row4 = WIFI_SSID
    DisplayI2C.display_row6 = "Initializing"
    DisplayI2C.displayRefresh()

    #Initialize WiFi Turn off and On to reset
    wlan = network.WLAN(network.STA_IF)

    try:
        wlan.active(False)
    except Exception:
        pass
    sleep(.25)

    try:
        wlan.active(True)
    except Exception:
        pass
    sleep(.25)

    #Disable power saving on Pico W WiFi chip for reliability
    try:
        wlan.config(pm=0xa11140)
    except Exception:
        pass
    wlan.disconnect()
    sleep(1)

    #Scan for networks
    nets = []
    try:
        nets = wlan.scan()
        print("Nearby networks (scan):", [_decode_ssid(n[0]) for n in nets])
    except Exception as e:
        print("Network scan failed:", e)

    ssid_found = _ssid_in_scan(nets, WIFI_SSID)
    if not ssid_found:
        print("Configured SSID not seen in scan:", WIFI_SSID)

    #Connect to WiFi
    try:
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except Exception as e:
        print("wlan.connect() raised:", e)

    if MAX_WIFI_WAIT is None:
        wifiWait = 30  # Default to 30 seconds if not set
    else:
        wifiWait = MAX_WIFI_WAIT
    
    DisplayI2C.display_row6 = "Time Remaining"

    last_status = None
    fail_reason = None

    while wifiWait > 0:
        if wlan.isconnected():
            break

        try:
            last_status = wlan.status()
        except Exception:
            last_status = None

        # Break early on definitive errors.
        if last_status in (-3, -2, -1):
            if last_status == -3:
                fail_reason = "password_incorrect"
            elif last_status == -2:
                fail_reason = "no_ssid_found"
            else:
                fail_reason = "connect_failed"
            break

        wifiWait -= 1
        DisplayI2C.display_row7 = str(wifiWait)
        DisplayI2C.displayRefresh()
        if last_status is None:
            print('waiting for connection...')
        else:
            print('waiting for connection... status=', _wlan_status_name(last_status))
        sleep(1)

    # Post-wait: classify result + (if connected) check internet.
    if not wlan.isconnected():
        # If scan didn't see it, prefer SSID-not-found even if status is generic.
        if fail_reason is None:
            if not ssid_found:
                fail_reason = "no_ssid_found"
            elif last_status == -3:
                fail_reason = "password_incorrect"
            else:
                fail_reason = "connect_failed"

        DisplayI2C.display_row6 = "WiFi Failed"
        if fail_reason == "no_ssid_found":
            DisplayI2C.display_row7 = "AP Not Found"
        elif fail_reason == "password_incorrect":
            DisplayI2C.display_row7 = "Bad Password"
        else:
            DisplayI2C.display_row7 = "Connection ERR"
        DisplayI2C.displayRefresh()

        print("WiFi connect failed. reason=", fail_reason, "status=", _wlan_status_name(last_status))
        return {
            "wifi_connected": False,
            "internet_ok": False,
            "reason": fail_reason,
            "status": last_status,
            "ssid_found": ssid_found,
        }

    # Connected to WiFi (has IP) - show IP then verify internet.
    try:
        ip = wlan.ifconfig()[0]
    except Exception:
        ip = None

    DisplayI2C.display_row6 = "Connected"
    DisplayI2C.displayRefresh()

    internet_ok = _internet_check_google()
    if internet_ok:
        sync_time_ntp()
        DisplayI2C.display_row6 = "Internet Check"
        DisplayI2C.display_row7 = "Passed"
    else:
        DisplayI2C.display_row6 = "Internet Check"
        DisplayI2C.display_row7 = "Failed"
    DisplayI2C.displayRefresh()
    sleep(1)

    print("WiFi connected. ip=", ip, "internet_ok=", internet_ok)
    return {
        "wifi_connected": True,
        "internet_ok": internet_ok,
        "reason": None if internet_ok else "no_internet",
        "status": last_status,
        "ssid_found": ssid_found,
        "ip": ip,
    }







