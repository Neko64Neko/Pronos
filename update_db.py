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
    url = "https://votre-api-endpoint.com/matches"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "votre-api-host.com"
    }
    
    response = requests.get(url, headers=headers)
    matches = response.json()
    
    for match in matches:
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
