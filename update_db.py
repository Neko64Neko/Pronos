import os
import requests
from supabase import create_client

# Récupération automatique depuis les secrets GitHub
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_update():
    # URL de l'API (à remplacer par la vôtre)
    url = "https://rugbyapi2.p.rapidapi.com/api/rugby/matches/live"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    response = requests.get(url, headers=headers)
    data = response.json()
    
    # --- AJOUTEZ CE BLOC DE SÉCURITÉ ---
    if 'message' in data and 'subscribed' in data['message'].lower():
        print(f"ERREUR : Vous n'êtes pas abonné à l'API. Allez sur RapidAPI pour cliquer sur 'Subscribe'.")
        return # On arrête le script ici, proprement
    
    # Si d'autres erreurs surviennent
    if not isinstance(data, list) and 'message' in data:
        print(f"Erreur API : {data['message']}")
        return
    # ------------------------------------
    
    for match in data:
        data = {
            "external_id": match['id'],
            "statut": match['status']['type'],
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "score_dom": match['homeScore']['current'],
            "score_ext": match['awayScore']['current']
        }
        supabase.table("Matchs").upsert(data, on_conflict="external_id").execute()

if __name__ == "__main__":
    run_update()
