"""Weather via Open-Meteo (free, no API key). Location comes from the
argument, WEATHER_LOCATION in .env, or IP geolocation, in that order."""
import time

from .. import config

_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

_place_cache = {}
_data_cache = {}  # place name -> (fetched_at, data)
_CACHE_SECONDS = 600


def _locate(location):
    import requests

    key = (location or "").strip().lower()
    if key in _place_cache:
        return _place_cache[key]
    if key:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=10,
        )
        resp.raise_for_status()
        hits = resp.json().get("results") or []
        if not hits:
            raise ValueError("Couldn't find a place called {!r}".format(location))
        h = hits[0]
        place = (h["latitude"], h["longitude"], ", ".join(
            x for x in (h.get("name"), h.get("country")) if x
        ))
    else:
        place = _locate_by_ip()
    _place_cache[key] = place
    return place


def _locate_by_ip():
    """Free IP geolocation services rate-limit aggressively; try a few."""
    import requests

    providers = [
        ("https://ipwho.is/", "latitude", "longitude", "city", "country"),
        ("http://ip-api.com/json/", "lat", "lon", "city", "country"),
        ("https://ipapi.co/json/", "latitude", "longitude", "city", "country_name"),
    ]
    errors = []
    for url, lat, lon, city, country in providers:
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            j = resp.json()
            return j[lat], j[lon], ", ".join(x for x in (j.get(city), j.get(country)) if x)
        except Exception as exc:  # noqa: BLE001 — fall through to the next one
            errors.append(str(exc))
    raise RuntimeError(
        "Couldn't work out your location; set WEATHER_LOCATION in .env. ({})".format(
            "; ".join(errors)
        )
    )


def data(location=None):
    """Structured weather for the HUD panel and the tool."""
    import requests

    location = location or config.WEATHER_LOCATION
    lat, lon, name = _locate(location)
    cached = _data_cache.get(name)
    if cached and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 3,
        },
        timeout=10,
    )
    resp.raise_for_status()
    j = resp.json()
    cur = j["current"]
    daily = j["daily"]
    result = {
        "place": name,
        "temp": round(cur["temperature_2m"]),
        "feels_like": round(cur["apparent_temperature"]),
        "humidity": cur["relative_humidity_2m"],
        "wind_kmh": round(cur["wind_speed_10m"]),
        "code": cur["weather_code"],
        "condition": _CODES.get(cur["weather_code"], "unknown"),
        "is_day": bool(cur.get("is_day", 1)),
        "days": [
            {
                "date": daily["time"][i],
                "high": round(daily["temperature_2m_max"][i]),
                "low": round(daily["temperature_2m_min"][i]),
                "rain_chance": daily["precipitation_probability_max"][i],
                "condition": _CODES.get(daily["weather_code"][i], "unknown"),
            }
            for i in range(len(daily["time"]))
        ],
    }
    _data_cache[name] = (time.time(), result)
    return result


def get(location=None):
    d = data(location)
    lines = [
        "{}: {}, {}°C (feels like {}°C), humidity {}%, wind {} km/h.".format(
            d["place"], d["condition"], d["temp"], d["feels_like"],
            d["humidity"], d["wind_kmh"],
        )
    ]
    for day in d["days"]:
        lines.append("{}: {}, high {}°C, low {}°C, {}% chance of rain.".format(
            day["date"], day["condition"], day["high"], day["low"],
            day["rain_chance"] if day["rain_chance"] is not None else 0,
        ))
    return "\n".join(lines)
