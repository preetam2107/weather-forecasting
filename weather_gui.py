import json
import os
import queue
import re
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from tkinter import messagebox, ttk

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_history.json")
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_HISTORY = 6

WEATHER_CODES = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "❄️"), 75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "❄️"), 80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"),
    82: ("Violent showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm, hail", "⛈️"), 99: ("Thunderstorm, hail", "⛈️"),
}


def describe(code):
    return WEATHER_CODES.get(code, ("Unknown", "❓"))


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "TkinterWeatherApp/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode(city):
    """Convert a city name to coordinates."""
    query = urllib.parse.urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    data = fetch_json(f"{GEOCODE_URL}?{query}")
    results = data.get("results")
    if not results:
        raise LookupError(f"City '{city}' was not found. Check the spelling.")
    return results[0]


def get_weather(lat, lon, fahrenheit):
    query = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "weather_code,wind_speed_10m,surface_pressure",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 5,
        "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
        "wind_speed_unit": "mph" if fahrenheit else "kmh",
    })
    return fetch_json(f"{FORECAST_URL}?{query}")


class WeatherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Weather App")
        self.geometry("720x580")
        self.minsize(680, 540)

        self.results = queue.Queue()
        self.location = None
        self.history = self.load_history()

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.build_ui()
        self.poll_results()

        if self.history:
            self.city_var.set(self.history[0])
            self.start_fetch(self.history[0])

    def build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="City:").pack(side="left")
        self.city_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.city_var, width=28)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self.on_search())
        entry.focus_set()

        self.search_btn = ttk.Button(top, text="Search", command=self.on_search)
        self.search_btn.pack(side="left")

        ttk.Label(top, text="  Recent:").pack(side="left")
        self.recent = ttk.Combobox(top, values=self.history, state="readonly", width=16)
        self.recent.pack(side="left", padx=6)
        self.recent.bind("<<ComboboxSelected>>", self.on_recent)

        self.unit_var = tk.StringVar(value="C")
        unit_frame = ttk.Frame(top)
        unit_frame.pack(side="right")
        for label in ("C", "F"):
            ttk.Radiobutton(unit_frame, text=f"°{label}", value=label,
                            variable=self.unit_var, command=self.on_unit_change).pack(side="left")

        card = tk.Frame(self, bg="#2c3e50", padx=20, pady=15)
        card.pack(fill="x", padx=12, pady=6)

        self.city_label = tk.Label(card, text="Search for a city", bg="#2c3e50", fg="white",
                                   font=("Segoe UI", 16, "bold"))
        self.city_label.pack(anchor="w")
        self.time_label = tk.Label(card, text="", bg="#2c3e50", fg="#bdc3c7",
                                   font=("Segoe UI", 9))
        self.time_label.pack(anchor="w")

        main = tk.Frame(card, bg="#2c3e50")
        main.pack(fill="x", pady=8)
        self.icon_label = tk.Label(main, text="🌍", bg="#2c3e50", fg="white",
                                   font=("Segoe UI Emoji", 46))
        self.icon_label.pack(side="left")
        temp_box = tk.Frame(main, bg="#2c3e50")
        temp_box.pack(side="left", padx=15)
        self.temp_label = tk.Label(temp_box, text="--", bg="#2c3e50", fg="white",
                                   font=("Segoe UI", 38, "bold"))
        self.temp_label.pack(anchor="w")
        self.cond_label = tk.Label(temp_box, text="", bg="#2c3e50", fg="#ecf0f1",
                                   font=("Segoe UI", 12))
        self.cond_label.pack(anchor="w")

        details = tk.Frame(card, bg="#2c3e50")
        details.pack(fill="x", pady=(5, 0))
        self.detail_vars = {}
        for i, name in enumerate(("Feels like", "Humidity", "Wind", "Pressure")):
            box = tk.Frame(details, bg="#34495e", padx=10, pady=6)
            box.grid(row=0, column=i, padx=4, sticky="ew")
            details.columnconfigure(i, weight=1)
            tk.Label(box, text=name, bg="#34495e", fg="#bdc3c7",
                     font=("Segoe UI", 9)).pack()
            var = tk.StringVar(value="--")
            tk.Label(box, textvariable=var, bg="#34495e", fg="white",
                     font=("Segoe UI", 11, "bold")).pack()
            self.detail_vars[name] = var

        ttk.Label(self, text="5-Day Forecast", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=14, pady=(8, 2))
        self.forecast_frame = ttk.Frame(self, padding=(8, 0))
        self.forecast_frame.pack(fill="x")
        self.forecast_boxes = []
        for i in range(5):
            box = tk.Frame(self.forecast_frame, bg="#ecf0f1", padx=8, pady=8, bd=1, relief="solid")
            box.grid(row=0, column=i, padx=4, sticky="nsew")
            self.forecast_frame.columnconfigure(i, weight=1)
            labels = {
                "day": tk.Label(box, text="--", bg="#ecf0f1", font=("Segoe UI", 10, "bold")),
                "icon": tk.Label(box, text="", bg="#ecf0f1", font=("Segoe UI Emoji", 22)),
                "temp": tk.Label(box, text="", bg="#ecf0f1", font=("Segoe UI", 10)),
                "rain": tk.Label(box, text="", bg="#ecf0f1", fg="#2980b9", font=("Segoe UI", 9)),
            }
            for label in labels.values():
                label.pack()
            self.forecast_boxes.append(labels)

        self.status_var = tk.StringVar(value="Enter a city name and press Search.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w",
                  padding=(8, 2)).pack(fill="x", side="bottom")

    def load_history(self):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [c for c in data if isinstance(c, str)][:MAX_HISTORY]
        except (OSError, json.JSONDecodeError):
            return []

    def save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f)
        except OSError:
            pass

    def add_history(self, city):
        self.history = [c for c in self.history if c.lower() != city.lower()]
        self.history.insert(0, city)
        self.history = self.history[:MAX_HISTORY]
        self.recent["values"] = self.history
        self.save_history()

    def on_search(self):
        city = self.city_var.get().strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z .,'\-]{1,49}", city):
            messagebox.showwarning("Invalid input",
                                   "Enter a valid city name (letters and spaces only).")
            return
        self.start_fetch(city)

    def on_recent(self, _event):
        city = self.recent.get()
        self.city_var.set(city)
        self.start_fetch(city)

    def on_unit_change(self):
        if self.location:
            self.start_fetch(None, self.location)

    def start_fetch(self, city, location=None):
        self.search_btn.config(state="disabled")
        self.status_var.set("Fetching weather...")
        fahrenheit = self.unit_var.get() == "F"
        threading.Thread(target=self.worker, args=(city, location, fahrenheit),
                         daemon=True).start()

    def worker(self, city, location, fahrenheit):
        """Runs in a background thread so the window never freezes."""
        try:
            if location is None:
                location = geocode(city)
            weather = get_weather(location["latitude"], location["longitude"], fahrenheit)
            self.results.put(("ok", location, weather))
        except LookupError as err:
            self.results.put(("error", str(err)))
        except urllib.error.HTTPError as err:
            self.results.put(("error", f"Server error ({err.code}). Try again later."))
        except (urllib.error.URLError, TimeoutError):
            self.results.put(("error", "Could not connect. Check your internet connection."))
        except (json.JSONDecodeError, KeyError, ValueError):
            self.results.put(("error", "Received unexpected data from the weather service."))

    def poll_results(self):
        """Checks the queue every 100 ms and updates widgets on the UI thread."""
        try:
            while True:
                message = self.results.get_nowait()
                self.search_btn.config(state="normal")
                if message[0] == "ok":
                    self.show_weather(message[1], message[2])
                else:
                    self.status_var.set("Error: " + message[1])
                    messagebox.showerror("Weather error", message[1])
        except queue.Empty:
            pass
        self.after(100, self.poll_results)

    def show_weather(self, location, data):
        self.location = location
        current, units = data["current"], data["current_units"]
        daily = data["daily"]

        place = location["name"]
        extras = [x for x in (location.get("admin1"), location.get("country")) if x]
        self.city_label.config(text=", ".join([place] + extras))
        self.time_label.config(text="Updated: " + current["time"].replace("T", " "))

        description, emoji = describe(current["weather_code"])
        self.icon_label.config(text=emoji)
        self.temp_label.config(text=f"{round(current['temperature_2m'])}{units['temperature_2m']}")
        self.cond_label.config(text=description)

        self.detail_vars["Feels like"].set(
            f"{round(current['apparent_temperature'])}{units['apparent_temperature']}")
        self.detail_vars["Humidity"].set(
            f"{current['relative_humidity_2m']}{units['relative_humidity_2m']}")
        self.detail_vars["Wind"].set(
            f"{current['wind_speed_10m']} {units['wind_speed_10m']}")
        self.detail_vars["Pressure"].set(
            f"{round(current['surface_pressure'])} {units['surface_pressure']}")

        for i, boxes in enumerate(self.forecast_boxes):
            day = datetime.strptime(daily["time"][i], "%Y-%m-%d")
            _, day_emoji = describe(daily["weather_code"][i])
            high = round(daily["temperature_2m_max"][i])
            low = round(daily["temperature_2m_min"][i])
            rain = daily["precipitation_probability_max"][i]
            boxes["day"].config(text="Today" if i == 0 else day.strftime("%a %d"))
            boxes["icon"].config(text=day_emoji)
            boxes["temp"].config(text=f"{high}° / {low}°")
            boxes["rain"].config(text=f"💧 {rain}%" if rain is not None else "")

        self.add_history(place)
        self.status_var.set(f"Showing weather for {place}.")


if __name__ == "__main__":
    WeatherApp().mainloop()