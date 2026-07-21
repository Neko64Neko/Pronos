import os
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
    
    # On envoie les paramètres directement ici
    params = {
        "tournament_id": "420",
        "season_id": "98426" #SAISON 2026-2027!!!!
    }
    
    response = requests.get(url, headers=headers, params=params)
    
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

    # Exemple à intégrer dans votre fonction d'appel automatique
    try:
        # 1. Récupérer le compteur actuel depuis Supabase
        res = supabase.table("Configuration").select("api_request_count, api_request_logs").eq("id", "api_tracking").execute()
        if res.data:
            current_count = res.data[0].get("api_request_count", 0)
            current_logs = res.data[0].get("api_request_logs", []) or []
            
            # 2. Incrémenter et ajouter un log automatique
            new_count = current_count + 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_logs.insert(0, f"[{timestamp}] Appel automatique (ex: 3h du matin)")
            if len(current_logs) > 20:
                current_logs = current_logs[:20]
                
            # 3. Sauvegarder dans Supabase
            supabase.table("Configuration").update({
                "api_request_count": new_count,
                "api_request_logs": current_logs
            }).eq("id", "api_tracking").execute()
    except Exception as e:
        print(f"Erreur lors de la mise à jour automatique du compteur : {e}")

if __name__ == "__main__":
    run_calendar()
