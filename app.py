from flask import Flask, render_template, request, jsonify, abort
import requests
from functools import lru_cache
from datetime import datetime, timedelta
import threading
from typing import Dict, List, Optional
import time

app = Flask(__name__)
apikey = "4c63f17a"

# Configuración
CACHE_TIMEOUT = 3600  # 1 hora en segundos
ITEMS_PER_PAGE = 10
MAX_RETRIES = 3
RETRY_DELAY = 1  # segundos

class RateLimiter:
    def __init__(self, calls_per_day):
        self.calls_per_day = calls_per_day
        self.calls = 0
        self.reset_time = datetime.now() + timedelta(days=1)
        self.lock = threading.Lock()

    def can_make_call(self) -> bool:
        with self.lock:
            now = datetime.now()
            if now >= self.reset_time:
                self.calls = 0
                self.reset_time = now + timedelta(days=1)
            
            if self.calls < self.calls_per_day:
                self.calls += 1
                return True
            return False

# Instancia del rate limiter (OMDB tiene límite de 1000 llamadas diarias en plan free)
rate_limiter = RateLimiter(calls_per_day=1000)

@lru_cache(maxsize=1000)
def searchfilms(search_text: str, page: int) -> Optional[dict]:
    """Busca películas con caché y control de rate limit"""
    if not rate_limiter.can_make_call():
        abort(429, description="API rate limit exceeded. Please try again later.")
    
    for attempt in range(MAX_RETRIES):
        try:
            url = f"https://www.omdbapi.com/?s={search_text}&page={page}&apikey={apikey}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                print(f"Failed to retrieve search results after {MAX_RETRIES} attempts: {e}")
                return None
            time.sleep(RETRY_DELAY)

@lru_cache(maxsize=1000)
def getmoviedetails(imdb_id: str) -> Optional[dict]:
    """Obtiene detalles de película con caché y control de rate limit"""
    if not rate_limiter.can_make_call():
        abort(429, description="API rate limit exceeded. Please try again later.")
    
    for attempt in range(MAX_RETRIES):
        try:
            url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={apikey}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                print(f"Failed to retrieve movie details after {MAX_RETRIES} attempts: {e}")
                return None
            time.sleep(RETRY_DELAY)

@lru_cache(maxsize=100)
def get_country_flag(fullname: str) -> Optional[str]:
    """Obtiene la bandera del país con caché"""
    for attempt in range(MAX_RETRIES):
        try:
            url = f"https://restcountries.com/v3.1/name/{fullname}?fullText=true"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            country_data = response.json()
            if country_data:
                return country_data[0].get("flags", {}).get("svg", None)
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                print(f"Failed to retrieve flag for country: {fullname}, error: {e}")
                return None
            time.sleep(RETRY_DELAY)
    return None

def merge_data_with_flags(filter: str, page: int = 1) -> List[Dict]:
    """Combina datos de películas con banderas, implementando paginación"""
    filmssearch = searchfilms(filter, page)
    if not filmssearch or "Search" not in filmssearch:
        return []

    # Calcular índices de paginación
    start_idx = 0
    end_idx = ITEMS_PER_PAGE
    page_movies = filmssearch["Search"][start_idx:end_idx]

    moviesdetailswithflags = []
    for movie in page_movies:
        moviedetails = getmoviedetails(movie["imdbID"])
        if not moviedetails:
            continue

        countries = []
        for country in (moviedetails.get("Country", "").split(",")):
            country = country.strip()
            if not country:
                continue
            
            flag = get_country_flag(country)
            countrywithflag = {
                "name": country,
                "flag": flag
            }
            countries.append(countrywithflag)

        moviewithflags = {
            "title": moviedetails["Title"],
            "year": moviedetails["Year"],
            "countries": countries
        }
        moviesdetailswithflags.append(moviewithflags)

    return moviesdetailswithflags

@app.route("/")
def index():
    filter = request.args.get("filter", "").upper()
    page = int(request.args.get("page", 1))
    movies = merge_data_with_flags(filter, page) if filter else []
    return render_template(
        "index.html",
        movies=movies,
        current_page=page,
        has_next=len(movies) == ITEMS_PER_PAGE
    )

@app.route("/api/movies")
def api_movies():
    filter = request.args.get("filter", "")
    page = int(request.args.get("page", 1))
    return jsonify(merge_data_with_flags(filter, page))

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify(error="Too many requests. Please try again later."), 429

if __name__ == "__main__":
    app.run(debug=True)