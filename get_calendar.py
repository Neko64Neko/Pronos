import os
import requests
from supabase import create_client

# Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_calendar():
    # 1. URL Calendrier (A adapter si l'endpoint est différent)
    url = "https://rugbyapi2.p.rapidapi.com/api/calendar/season/61643/2026/days-with-events"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    response = requests.get(url, headers=headers)
    
    # Vérification du code HTTP
    if response.status_code == 204:
        print("API connectée avec succès, mais aucun match à venir (204).")
        return # On arrête le script proprement sans crash
        
    # Si on arrive ici, c'est qu'on a du contenu (200 OK)
    data = response.json()
    
    # Maintenant on peut traiter data en toute sécurité
    events = data.get('events', [])
    
    events = data.get('events', [])

    if not events:
        print("Aucun match à venir trouvé.")
        return

    # 3. Préparation des données pour Supabase
    all_matches = []
    for match in events:
        # ATTENTION : Adapte ces clés selon ce que tu vois dans le print de debug
        match_data = {
            "external_id": match['id'],
            "statut": "scheduled", # Ou match['status']['type'] si dispo
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "date_match": match.get('date'), # Assure-toi que c'est bien la clé date
            "score_dom": 0, # Par défaut, car pas encore joué
            "score_ext": 0  # Par défaut
        }
        all_matches.append(match_data)
    
    # 4. Upsert en masse
    if all_matches:
        supabase.table("Matchs").upsert(all_matches, on_conflict="external_id").execute()
        print(f"{len(all_matches)} matchs mis à jour/ajoutés au calendrier.")

if __name__ == "__main__":
    run_calendar()
