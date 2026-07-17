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
    events = data.get('events', [])

    if not events:
        print("Aucun match trouvé.")
        return

    for match in events:
        # On vérifie si le tournoi correspond à l'ID 420
        # Attention : vérifie bien le chemin vers l'ID du tournoi dans ton JSON (ex: match['tournament']['id'])
        if str(match['tournament']['id']) != "420":
            continue # On ignore les autres matchs
            
        # Si c'est le bon tournoi, on continue le traitement
        match_data = {
            "external_id": match['id'],
            "statut": match['status']['type'],
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "score_dom": match['homeScore']['current'],
            "score_ext": match['awayScore']['current']
        }
        
        # Upsert avec la variable renommée
        supabase.table("Matchs").upsert([match_data], on_conflict="external_id").execute()
        
if __name__ == "__main__":
    run_update()
