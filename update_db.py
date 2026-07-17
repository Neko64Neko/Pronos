import requests
from supabase import create_client

# --- CONFIGURATION ---
SUPABASE_URL = "VOTRE_URL_SUPABASE"
SUPABASE_KEY = "VOTRE_CLE_SUPABASE"
API_URL = "L_URL_DE_VOTRE_API_DE_MATCHS" # L'URL où vous récupérez les matchs

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_and_update():
    # 1. Récupérer les données de l'API
    response = requests.get(API_URL)
    matches = response.json() # On suppose que l'API renvoie une liste de matchs

    # 2. Boucler sur chaque match
    for match in matches:
        data_to_upsert = {
            "external_id": match['id'], # Le fameux external_id
            "statut": match['status']['type'],
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "score_dom": match['homeScore']['current'],
            "score_ext": match['awayScore']['current']
        }
        
        # 3. Envoyer dans Supabase (Upsert : met à jour si l'id existe, crée sinon)
        supabase.table("Matchs").upsert(data_to_upsert, on_conflict="external_id").execute()
        print(f"Match {match['id']} synchronisé !")

if __name__ == "__main__":
    try:
        fetch_and_update()
        print("Mise à jour terminée avec succès.")
    except Exception as e:
        print(f"Une erreur est survenue : {e}")
