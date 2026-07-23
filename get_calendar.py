import os
from datetime import datetime
import requests
from supabase import create_client

print("--- LE SCRIPT COMMENCE ---")

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

# --- COMPTEUR API AVEC DEBUG VISIBLE ---
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Lecture
        res = supabase.table("Configuration").select("*").execute()
        print("DEBUG - Données lues dans Supabase :", res.data)
        
        if res.data and len(res.data) > 0:
            ligne_config = res.data[0]
            target_id = ligne_config.get("id")
            
            saved_date = ligne_config.get("last_reset_date")
            current_logs = ligne_config.get("api_request_logs", []) or []
            
            # Gestion du reset journalier
            if saved_date != today_str:
                current_count = 0
            else:
                current_count = int(ligne_config.get("api_request_count", 0) or 0)
            
            new_count = current_count + 1
            current_logs.insert(0, f"[{timestamp}] MAJ Calendrier (Automatique)")
            if len(current_logs) > 20:
                current_logs = current_logs[:20]
                
            print(f"DEBUG - Valeurs calculées -> New count: {new_count}, Logs: {current_logs}")

            # 2. Écriture / Update
            response_update = supabase.table("Configuration").update({
                "api_request_count": new_count,
                "last_reset_date": today_str,
                "api_request_logs": current_logs
            }).eq("id", target_id).execute()
            
            print("DEBUG - Réponse de Supabase après update :", response_update)
            print(f"Succès ! Requêtes aujourd'hui : {new_count}")
        else:
            print("ERREUR : Aucune ligne trouvée dans la table Configuration.")
            
    except Exception as e:
        print("ERREUR CRITIQUE DÉTECTÉE DANS LE COMPTEUR :", e)

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
