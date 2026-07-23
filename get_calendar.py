import os
from datetime import datetime
import requests
from supabase import create_client

# Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_calendar():
    url = "https://rugbyapi2.p.rapidapi.com/api/rugby/getTournamentUpcomingMatches"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    params = {
        "tournament_id": "420",
        "season_id": "98426" # SAISON 2026-2027
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    # --- COMPTAGE IMMÉDIAT DE LA REQUÊTE API ---
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        res = supabase.table("Configuration").select("*").eq("id", "default_config").execute()
        current_count = 0
        current_logs = []
        
        if res.data:
            config_api = res.data[0]
            saved_date = config_api.get("last_reset_date")
            current_logs = config_api.get("api_request_logs", []) or []
            
            if saved_date != today_str:
                current_count = 0
            else:
                current_count = config_api.get("api_request_count", 0)
        
        new_count = current_count + 1
        current_logs.insert(0, f"[{timestamp}] MAJ Calendrier (Automatique)")
        if len(current_logs) > 20:
            current_logs = current_logs[:20]
            
        supabase.table("Configuration").upsert({
            "id": "default_config",
            "api_request_count": new_count,
            "last_reset_date": today_str,
            "api_request_logs": current_logs
        }, on_conflict="id").execute()
        
        print(f"Suivi API mis à jour : {new_count} requêtes aujourd'hui.")
    except Exception as e:
        print(f"Erreur lors de la mise à jour automatique du compteur : {e}")
    # -------------------------------------------

    # Vérification du code HTTP
    if response.status_code == 204:
        print("API connectée avec succès, mais aucun match à venir (204).")
        return
        
    data = response.json()
    events = data.get('events', [])

    if not events:
        print("Aucun match à venir trouvé.")
        return

    # Préparation des données pour Supabase
    all_matches = []
    for match in events:
        match_data = {
            "external_id": match['id'],
            "statut": "scheduled",
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "date_match": match.get('date'),
            "score_dom": 0,
            "score_ext": 0
        }
        all_matches.append(match_data)
    
    # Upsert en masse des matchs
    if all_matches:
        supabase.table("Matchs").upsert(all_matches, on_conflict="external_id").execute()
        print(f"{len(all_matches)} matchs mis à jour/ajoutés au calendrier.")
