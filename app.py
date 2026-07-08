"""
Real-Time Air Pollution Monitoring Dashboard
All sources are FREE — no API key required.

  Geocoding  : Nominatim (OpenStreetMap)
  AQI + Pollutants : Open-Meteo Air Quality API
  Weather    : Open-Meteo Forecast API
  Map        : OpenStreetMap iframe

Run:  python app.py
Open: http://127.0.0.1:5000
"""

import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

NOM_HEADERS = {"User-Agent": "AirWatchDashboard/1.0"}


# ── AQI classification (US AQI scale) ─────────────────────────────────────────
def classify_aqi(aqi: int) -> dict:
    if aqi <= 50:
        return {
            "category":   "Good",
            "hex":        "#28a745", 
            "level":      "good",
            "health_msg": "Air quality is satisfactory. Safe to be outdoors.",
            "suggestion": "Great day for outdoor sports, jogging, or cycling!",
        }
    elif aqi <= 100:
        return {
            "category":   "Moderate",
            "hex":        "#ffc107",
            "level":      "moderate",
            "health_msg": "Acceptable air quality. Unusually sensitive people should limit prolonged outdoor exertion.", 
            "suggestion": "Light outdoor activities are fine. Sensitive individuals should take caution.",
        }
    elif aqi <= 150:
        return {
            "category":   "Unhealthy for Sensitive Groups",
            "hex":        "#fd7e14",
            "level":      "sensitive",
            "health_msg": "Sensitive groups may experience health effects.",
            "suggestion": "Sensitive groups should limit outdoor activities. Others may continue light activities.",
        }
    else:
        return {
            "category":   "Unhealthy",
            "hex":        "#dc3545",
            "level":      "unhealthy",
            "health_msg": "Everyone may begin to experience health effects. Avoid outdoor activity.",
            "suggestion": "Stay indoors. Keep windows closed and use air purifiers if available.",
        }


# ── Geocode city → lat/lon via Nominatim ──────────────────────────────────────
def geocode(city: str, state: str, country: str):
    q = f"{city}, {state}, {country}"
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": q, "format": "json", "limit": 1, "accept-language": "en"},
        headers=NOM_HEADERS,
        timeout=8,
    )
    r.encoding = "utf-8"
    res = r.json()
    if not res:
        raise ValueError(f"Location '{q}' not found. Check city, state, and country spelling.")
    return float(res[0]["lat"]), float(res[0]["lon"])


# ── Fetch AQI + pollutants from Open-Meteo Air Quality ────────────────────────
def fetch_air_quality(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude":  lat,
            "longitude": lon,
            "current":   "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
                         "sulphur_dioxide,ozone,us_aqi",
        },
        timeout=10,
    )
    r.raise_for_status()
    cur = r.json().get("current", {})
    print("AIR QUALITY RESPONSE:", cur)

    aqi = cur.get("us_aqi")
    if aqi is None:
        raise ValueError("Real-time AQI data not available for this location.")

    # Determine main pollutant using AQI-relative normalisation
    # Divide each reading by its WHO/EPA threshold so values are comparable
    thresholds = {
        "PM2.5": (cur.get("pm2_5"),            12.0),
        "PM10":  (cur.get("pm10"),             50.0),
        "NO2":   (cur.get("nitrogen_dioxide"), 53.0),
        "O3":    (cur.get("ozone"),            70.0),
        "CO":    (cur.get("carbon_monoxide"),  4400.0),  # µg/m³ raw
        "SO2":   (cur.get("sulphur_dioxide"),  35.0),
    }
    scores = {k: v / t for k, (v, t) in thresholds.items() if v is not None}
    main_pollutant = max(scores, key=scores.get) if scores else "PM2.5"

    return {
        "aqi":      int(aqi),
        "pollutant": main_pollutant,
        "pm25":     round(cur["pm2_5"],   2) if cur.get("pm2_5")             is not None else None,
        "pm10":     round(cur["pm10"],    2) if cur.get("pm10")              is not None else None,
        "no2":      round(cur["nitrogen_dioxide"], 2) if cur.get("nitrogen_dioxide") is not None else None,
        "o3":       round(cur["ozone"],   2) if cur.get("ozone")             is not None else None,
        "co":       round(cur["carbon_monoxide"] / 1000, 2) if cur.get("carbon_monoxide") is not None else None,
        "so2":      round(cur["sulphur_dioxide"], 2) if cur.get("sulphur_dioxide") is not None else None,
    }


# ── Fetch weather from Open-Meteo Forecast ────────────────────────────────────
def fetch_weather(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":        lat,
            "longitude":       lon,
            "current":         "temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure",
            "wind_speed_unit": "ms",
            "forecast_days":   1,
        },
        timeout=8,
    )
    r.raise_for_status()
    cur = r.json().get("current", {})
    print("WEATHER RESPONSE:", cur)
    return {
        "temperature": cur.get("temperature_2m"),
        "humidity":    cur.get("relative_humidity_2m"),
        "wind_speed":  round(cur["wind_speed_10m"], 2) if cur.get("wind_speed_10m") is not None else None,
        "pressure":    cur.get("surface_pressure"),
    }


# ── Reverse geocode lat/lon → city, state, country via Nominatim ──────────────
def reverse_geocode(lat: float, lon: float) -> tuple:
    r = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lon, "format": "json", "accept-language": "en"},
        headers=NOM_HEADERS,
        timeout=8,
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    addr = r.json().get("address", {})
    city    = (addr.get("city") or addr.get("town") or
               addr.get("village") or addr.get("county") or "Unknown")
    state   = addr.get("state", "")
    country = addr.get("country", "")
    return city, state, country


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_aqi_by_coords")
def get_aqi_by_coords():
    """Called when user clicks 'Use My Location' — browser sends lat/lon."""
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "Valid lat and lon are required."}), 400

    try:
        # Reverse geocode to get human-readable location
        city, state, country = reverse_geocode(lat, lon)
        print(f"REVERSE GEOCODE: lat={lat}, lon={lon} city={city}, state={state}, country={country}")

        aq = fetch_air_quality(lat, lon)

        try:
            wx = fetch_weather(lat, lon)
        except Exception:
            wx = {"temperature": None, "humidity": None, "wind_speed": None, "pressure": None}

        info = classify_aqi(aq["aqi"])

        return jsonify({
            "aqi":         aq["aqi"],
            "pollutant":   aq["pollutant"],
            "city":        city,
            "state":       state,
            "country":     country,
            "lat":         lat,
            "lon":         lon,
            "temperature": wx["temperature"],
            "humidity":    wx["humidity"],
            "wind_speed":  wx["wind_speed"],
            "pressure":    wx["pressure"],
            "pm25":        aq["pm25"],
            "pm10":        aq["pm10"],
            "no2":         aq["no2"],
            "o3":          aq["o3"],
            "co":          aq["co"],
            "so2":         aq["so2"],
            "updated":     "",
            "source":      "Open-Meteo",
            "category":    info["category"],
            "hex":         info["hex"],
            "level":       info["level"],
            "health_msg":  info["health_msg"],
            "suggestion":  info["suggestion"],
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Network error. Check your internet connection."}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/get_aqi")
def get_aqi():
    city    = request.args.get("city",    "").strip()
    state   = request.args.get("state",   "").strip()
    country = request.args.get("country", "").strip()

    if not city or not state or not country:
        return jsonify({"error": "City, state, and country are all required."}), 400

    try:
        # Step 1: geocode → correct lat/lon
        lat, lon = geocode(city, state, country)
        print(f"GEOCODE: {city}, {state}, {country} lat={lat}, lon={lon}")

        # Step 2: real AQI + pollutants
        aq = fetch_air_quality(lat, lon)
        
        # Step 3: weather
        try:
            wx = fetch_weather(lat, lon)
        except Exception:
            wx = {"temperature": None, "humidity": None, "wind_speed": None, "pressure": None}

        info = classify_aqi(aq["aqi"])

        return jsonify({
            "aqi":         aq["aqi"],
            "pollutant":   aq["pollutant"],
            "city":        city,
            "state":       state,
            "country":     country,
            "lat":         lat,
            "lon":         lon,
            "temperature": wx["temperature"],
            "humidity":    wx["humidity"],
            "wind_speed":  wx["wind_speed"],
            "pressure":    wx["pressure"],
            "pm25":        aq["pm25"],
            "pm10":        aq["pm10"],
            "no2":         aq["no2"],
            "o3":          aq["o3"],
            "co":          aq["co"],
            "so2":         aq["so2"],
            "updated":     "",
            "source":      "Open-Meteo",
            "category":    info["category"],
            "hex":         info["hex"],
            "level":       info["level"],
            "health_msg":  info["health_msg"],
            "suggestion":  info["suggestion"],
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Network error. Check your internet connection."}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
