"""Lector NMEA no bloqueante para GPS UART del T190."""

import time


def _checksum_ok(sentence):
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, checksum = sentence[1:].partition("*")
    value = 0
    for char in body:
        value ^= ord(char)
    try:
        return value == int(checksum[:2], 16)
    except ValueError:
        return False


def _coordinate(raw, hemisphere):
    if not raw or hemisphere not in ("N", "S", "E", "W"):
        return None
    value = float(raw)
    degrees = int(value / 100)
    minutes = value - degrees * 100
    limit = 90 if hemisphere in ("N", "S") else 180
    if minutes >= 60 or degrees > limit or (degrees == limit and minutes > 0):
        return None
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _is_leap_year(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _previous_day(year, month, day):
    if day > 1:
        return year, month, day - 1
    if month == 1:
        year -= 1
        month = 12
    else:
        month -= 1
    month_days = (31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30,
                  31, 31, 30, 31, 30, 31)
    return year, month, month_days[month - 1]


def _art_datetime(raw_time, raw_date):
    if len(raw_time) < 6 or len(raw_date) != 6:
        return None
    try:
        hour = int(raw_time[0:2])
        minute = int(raw_time[2:4])
        second = int(raw_time[4:6])
        day = int(raw_date[0:2])
        month = int(raw_date[2:4])
        short_year = int(raw_date[4:6])
    except ValueError:
        return None

    year = 2000 + short_year if short_year < 80 else 1900 + short_year
    if (hour > 23 or minute > 59 or second > 59 or month < 1 or month > 12):
        return None
    month_days = (31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30,
                  31, 31, 30, 31, 30, 31)
    if day < 1 or day > month_days[month - 1]:
        return None

    hour -= 3
    if hour < 0:
        hour += 24
        year, month, day = _previous_day(year, month, day)
    return year, month, day, hour, minute, second


def _weekday_monday0(year, month, day):
    offsets = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    adjusted_year = year - (1 if month < 3 else 0)
    sunday0 = (adjusted_year + adjusted_year // 4 - adjusted_year // 100 +
               adjusted_year // 400 + offsets[month - 1] + day) % 7
    return (sunday0 + 6) % 7


class GPSReceiver:
    def __init__(self, uart):
        self._uart = uart
        self._buffer = bytearray()
        self._discard_line = False
        self.invalid_bytes = 0
        self._fix = False
        self._latitude = None
        self._longitude = None
        self._satellites = 0
        self._speed_kmh = 0.0
        self._last_fix_ms = 0
        self._datetime_art = None
        self.time_update_count = 0

    def poll(self):
        """Consume any available UART bytes without waiting for a full sentence."""
        available = self._uart.any()
        if not available:
            return False
        chunk = self._uart.read(min(available, 256))
        if not chunk:
            return False

        updated = False
        for byte in chunk:
            if byte == 10:
                if self._discard_line:
                    self._buffer = bytearray()
                    self._discard_line = False
                    continue
                line = bytes(self._buffer).decode("ascii").strip()
                self._buffer = bytearray()
                if line:
                    updated = self._parse_sentence(line) or updated
            elif byte != 13:
                if self._discard_line:
                    continue
                if byte < 32 or byte > 126:
                    self.invalid_bytes += 1
                    self._buffer = bytearray()
                    self._discard_line = True
                    continue
                self._buffer.append(byte)
                if len(self._buffer) > 128:
                    self._buffer = bytearray()
                    self._discard_line = True
        return updated

    def _parse_sentence(self, sentence):
        if not _checksum_ok(sentence):
            return False
        fields = sentence.split(",")
        kind = fields[0][-3:]
        try:
            if kind == "GGA":
                fix_quality = int(fields[6] or "0")
                satellites = int(fields[7] or "0")
                latitude = _coordinate(fields[2], fields[3])
                longitude = _coordinate(fields[4], fields[5])
                self._satellites = satellites
                self._fix = fix_quality > 0 and latitude is not None and longitude is not None
                if self._fix:
                    self._latitude = latitude
                    self._longitude = longitude
                    self._last_fix_ms = time.ticks_ms()
                return True
            if kind == "RMC":
                valid = fields[2] == "A"
                if fields[7]:
                    self._speed_kmh = float(fields[7]) * 1.852 if valid else 0.0
                if valid and len(fields) > 9:
                    datetime_art = _art_datetime(fields[1], fields[9])
                    if datetime_art is not None:
                        self._datetime_art = datetime_art
                        self.time_update_count += 1
                return valid
        except (IndexError, ValueError, OverflowError):
            return False
        return False

    def has_fix(self, max_age_ms=3000):
        return self._fix and time.ticks_diff(time.ticks_ms(), self._last_fix_ms) <= max_age_ms

    @property
    def satellites(self):
        return self._satellites

    def latest_fix(self):
        if not self.has_fix():
            return None
        return {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "satellites": self._satellites,
            "speed_kmh": self._speed_kmh,
        }

    def latest_rtc_datetime(self):
        if self._datetime_art is None:
            return None
        year, month, day, hour, minute, second = self._datetime_art
        return (year, month, day, _weekday_monday0(year, month, day),
                hour, minute, second, 0)

    def latest_datetime_art(self):
        return self._datetime_art

    def deinit(self):
        self._uart.deinit()
