# LiveQuakes Pico Seismometer

A DIY earthquake-detecting seismometer built from a Raspberry Pi Pico 2 W and
an ST LSM6DSOX accelerometer, running MicroPython. It reports real shake
events to [LiveQuakes](https://livequakes.com)'s community stations network,
so this station's detections show up on the live public map right alongside
official USGS data.

Total hardware cost is well under $30 -- built as a cheap, hackable
alternative to a Raspberry Shake for anyone who wants to contribute real
sensor data.

![The finished sensor, mounted and reporting live](wall-mount.jpg)
*The finished sensor, mounted and reporting live. The green LED means it's powered and running.*

## How it works

The firmware polls the accelerometer as fast as I2C allows and runs a
classic seismology-style **STA/LTA** (short-term-average / long-term-average)
trigger -- the same class of algorithm real seismometer software (e.g.
ObsPy's `recursive_sta_lta`) uses. A short exponential moving average tracks
"what's happening right now," a long one tracks "the ambient noise floor,"
and a trigger fires when the ratio between them spikes. That adapts to
wherever you mount it, instead of using one fixed threshold that's too
twitchy in a noisy spot or too dead in a quiet one.

It uses the full 3-axis acceleration vector's *magnitude*, not a single
axis, so the sensor doesn't need to be mounted perfectly level or in any
particular orientation -- at rest, `|x, y, z|` is always ~1g regardless of
which way is "up" for the board.

When a trigger starts and ends, the firmware POSTs the event's peak
amplitude and duration to LiveQuakes' ingestion API, with automatic retries
in case the very first HTTPS/TLS handshake after boot flakes out (a known
quirk on constrained MicroPython WiFi stacks).

## Hardware

- Raspberry Pi Pico 2 W
- [Adafruit LSM6DSOX breakout](https://www.adafruit.com/product/4438) (accelerometer + gyro; only the accelerometer is used here)
- 4 wires (I2C: SDA, SCL, plus power and ground)

## Wiring

| LSM6DSOX | Pico 2 W    |
|----------|-------------|
| VIN      | 3V3 (OUT)   |
| GND      | GND         |
| SCL      | GP5         |
| SDA      | GP4         |

![Wiring detail: VIN to 3V3, SCL to GP5, SDA to GP4, GND to GND](wiring-labeled.jpg)

## Setup

1. Flash MicroPython onto the Pico 2 W if you haven't already.
2. In Thonny (or your MicroPython IDE of choice), install the `urequests`
   library: `import mip; mip.install("urequests")`.
3. Copy `config.py.example` to `config.py` and fill in your WiFi credentials.
4. Go to the **Community Stations** section on
   [livequakes.com](https://livequakes.com), sign in, and register a new
   station to get an API key. Paste it into `config.py` as
   `STATION_API_KEY`.
5. Upload `lsm6dsox.py`, `main.py`, and your filled-in `config.py` to the
   Pico's root, then power-cycle it (or run `main.py` from the IDE).
6. Watch the Shell/REPL output: it connects to WiFi, finds the sensor over
   I2C, warms up for 90 seconds, and then starts watching for triggers.
   When one fires, you'll see it reported, and your station will show up on
   the LiveQuakes map.

`config.py` is gitignored on purpose -- it holds your WiFi password and your
station's private API key. Never commit it.

## Tuning

The tunables at the top of `main.py` (trigger sensitivity, warmup time,
amplitude scaling, etc.) are commented inline. Set `DEBUG_STATUS = True`
(on by default) and watch the Shell/REPL output: it prints the live
STA/LTA ratio every few seconds so you can see where your ambient noise
floor actually sits before deciding how far to lower `TRIGGER_RATIO`.

To catch smaller tremors, lower `TRIGGER_RATIO` (default `2.5`, down from
an initial `4.0`) -- the lower it goes, the more sensitive, but also the
more prone to false triggers from footsteps or doors on a loose mount. If
your mount is picking up too much local noise, a more rigid mount
(bolted/clamped rather than sitting loose on a desk) helps more than
retuning thresholds.

**Testing gotcha:** `WARMUP_S` (default 90s) only blocks *triggering* --
the ambient-noise baseline keeps updating the whole time, warmup included.
Shaking the board to "test" it during warmup gets absorbed as normal
background noise and raises your effective threshold for a while after
warmup ends too. Power-cycle, leave it completely still for the full
warmup, *then* do a test shake.

## License

MIT -- see [LICENSE](LICENSE).
