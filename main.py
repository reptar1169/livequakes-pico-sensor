# main.py -- runs automatically on power-up (MicroPython convention: any file
# named main.py on the device root is run after boot).
#
# What this does: polls the LSM6DSOX as fast as I2C allows, and runs a
# classic seismology-style STA/LTA (short-term-average / long-term-average)
# trigger on the deviation of the acceleration vector's magnitude from its
# resting value. STA/LTA is what real seismometer software (e.g. ObsPy's
# recursive_sta_lta) uses too: a short EMA tracks "what's happening right
# now," a long EMA tracks "the ambient noise floor," and a trigger fires
# when the ratio between them spikes -- which adapts to your specific
# mounting location's normal vibration level instead of using one fixed
# threshold that might be too twitchy in a noisy spot or too dead in a
# quiet one.
#
# Using the acceleration vector's *magnitude* (not a single axis) means the
# sensor doesn't need to be mounted perfectly level or in any particular
# orientation -- at rest, |x,y,z| is always ~1g regardless of which way is
# "up" for the board.

import time
import network
import urequests
from machine import I2C, Pin
from lsm6dsox import LSM6DSOX
import config

# ---- Tunables ---------------------------------------------------------
I2C_SDA_PIN = 4
I2C_SCL_PIN = 5

STA_TAU_S = 0.5  # short-term average time constant (seconds)
LTA_TAU_S = 30.0  # long-term average time constant (seconds)
BASELINE_TAU_S = 120.0  # very slow EMA tracking the resting ~1g offset
WARMUP_S = 90  # ignore triggers for this long after boot, while STA/LTA settle

TRIGGER_RATIO = 4.0  # STA/LTA ratio that starts an event
DETRIGGER_RATIO = 1.3  # STA/LTA ratio that ends an event
TRIGGER_CONFIRM_SAMPLES = 3  # consecutive over-threshold samples required to fire
MIN_EVENT_MS = 300  # basic floor against instant one-sample blips; note that STA
# smoothing itself stretches a brief tap into a longer-looking event (a single
# knock can still end up reported as ~1s long), so this alone won't cleanly
# separate "someone bumped the table" from a real quake -- amplitude is the
# more reliable signal for that: a tap is a low peak-g event, a real quake is not.
AMPLITUDE_SCALE = 3000  # peak g-deviation * this = reported amplitude (0-1000, clipped)
# -------------------------------------------------------------------------


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for _ in range(30):
            if wlan.isconnected():
                break
            time.sleep(1)
    if wlan.isconnected():
        print("WiFi connected:", wlan.ifconfig()[0])
    else:
        print("WiFi did not connect -- check config.py. Will retry before the next report.")
    return wlan


REPORT_RETRIES = 3  # first HTTPS request after boot (or after a while idle) can
# fail once with a low-level socket error even when WiFi/DNS/TLS are all fine
# -- this has been observed in practice and isn't specific to this endpoint,
# so a real trigger gets a couple of quick retries rather than being dropped.
REPORT_RETRY_DELAY_S = 1.5


def _post_event(amplitude, duration_ms):
    resp = urequests.post(
        config.INGEST_URL,
        headers={"Content-Type": "application/json", "X-Api-Key": config.STATION_API_KEY},
        json={"amplitude": round(amplitude, 2), "durationMs": int(duration_ms)},
    )
    text = resp.text
    resp.close()
    return text


def report_event(wlan, amplitude, duration_ms):
    if not wlan.isconnected():
        wlan = connect_wifi()
    for attempt in range(1, REPORT_RETRIES + 1):
        try:
            print("Reported event:", _post_event(amplitude, duration_ms))
            return wlan
        except Exception as e:
            print("Report attempt %d/%d failed: %s" % (attempt, REPORT_RETRIES, e))
            if attempt < REPORT_RETRIES:
                time.sleep(REPORT_RETRY_DELAY_S)
    print("Giving up on this report after %d attempts." % REPORT_RETRIES)
    return wlan


def ema_alpha(dt, tau):
    return dt / (tau + dt)


def main():
    wlan = connect_wifi()

    i2c = I2C(0, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN), freq=400000)
    print("I2C devices found:", [hex(a) for a in i2c.scan()])
    sensor = LSM6DSOX(i2c)
    print("LSM6DSOX ready. Warming up for %ds..." % WARMUP_S)

    sta = 0.0
    lta = 0.0
    baseline = 1.0  # resting |acceleration| is ~1g in any orientation
    triggered = False
    trigger_start = 0
    peak_dev = 0.0
    confirm_count = 0

    boot_time = time.ticks_ms()
    last_t = boot_time

    while True:
        x, y, z = sensor.acceleration()
        mag = (x * x + y * y + z * z) ** 0.5

        now = time.ticks_ms()
        dt = time.ticks_diff(now, last_t) / 1000.0
        last_t = now
        if dt <= 0:
            continue

        dev = abs(mag - baseline)

        sta += (dev - sta) * ema_alpha(dt, STA_TAU_S)
        if not triggered:
            # Freeze LTA/baseline while an event is in progress, so a real
            # earthquake doesn't get absorbed into "the new normal" mid-shake.
            lta += (dev - lta) * ema_alpha(dt, LTA_TAU_S)
            baseline += (mag - baseline) * ema_alpha(dt, BASELINE_TAU_S)

        ratio = (sta / lta) if lta > 0.0005 else 0.0
        warmed_up = time.ticks_diff(now, boot_time) > WARMUP_S * 1000

        if not triggered:
            if warmed_up and ratio > TRIGGER_RATIO:
                confirm_count += 1
                if confirm_count >= TRIGGER_CONFIRM_SAMPLES:
                    triggered = True
                    trigger_start = now
                    peak_dev = dev
                    print("TRIGGER (ratio=%.2f)" % ratio)
            else:
                confirm_count = 0
        else:
            peak_dev = max(peak_dev, dev)
            if ratio < DETRIGGER_RATIO:
                duration_ms = time.ticks_diff(now, trigger_start)
                triggered = False
                confirm_count = 0
                print("de-trigger: peak=%.4fg duration=%dms" % (peak_dev, duration_ms))
                if duration_ms >= MIN_EVENT_MS:
                    amplitude = min(1000.0, peak_dev * AMPLITUDE_SCALE)
                    wlan = report_event(wlan, amplitude, duration_ms)


try:
    main()
except KeyboardInterrupt:
    print("Stopped.")
