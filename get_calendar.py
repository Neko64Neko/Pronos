import os
from datetime import datetime, timezone
import requests
from supabase import create_client

print("--- LE SCRIPT COMMENCE ---")

# Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_calendar():
    tournament_id = "420"
    season_id = "98426"
    
    # Nouvel endpoint validé
    url = f"https://rugbyapi2.p.rapidapi.com/api/rugby/tournament/{tournament_id}/season/{season_id}/matches/next/0"
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    print("Appel de l'API RapidAPI...")
    response = requests.get(url, headers=headers)
    print(f"Réponse API reçue avec le code statut : {response.status_code}")

    # --- MISE À JOUR DU COMPTEUR API DANS SUPABASE ---
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        res = supabase.table("Configuration").select("*").execute()
        
        if res.data and len(res.data) > 0:
            ligne_config = res.data[0]
            target_id = ligne_config.get("id")
            
            saved_date = ligne_config.get("last_reset_date")
            current_logs = ligne_config.get("api_request_logs", []) or []
            
            if saved_date != today_str:
                current_count = 0
            else:
                current_count = int(ligne_config.get("api_request_count", 0) or 0)
            
            new_count = current_count + 1
            current_logs.insert(0, f"[{timestamp}] MAJ Calendrier (Automatique)")
            if len(current_logs) > 20:
                current_logs = current_logs[:20]
                
            supabase.table("Configuration").update({
                "api_request_count": new_count,
                "last_reset_date": today_str,
                "api_request_logs": current_logs
            }).eq("id", target_id).execute()
            
            print(f"SUCCÈS : Compteur API mis à jour à {new_count} requêtes aujourd'hui.")
        else:
            print("ERREUR : Aucune ligne trouvée dans la table Configuration.")
            
    except Exception as e:
        print(f"ERREUR LORS DE LA MAJ DU COMPTEUR : {e}")

    # Vérification du code HTTP
    if response.status_code == 204:
        print("API connectée avec succès, mais aucun match à venir (204).")
        return
        
    data = response.json()
    
    # L'API renvoie directement une liste de matchs
    events = data if isinstance(data, list) else data.get('events', [])

    if not events:
        print("Aucun match à venir trouvé dans les données.")
        return

    # Préparation des données pour Supabase
    all_matches = []
    for match in events:
        # Conversion du timestamp Unix en format ISO pour Supabase
        start_timestamp = match.get('startTimestamp')
        date_match_iso = None
        if start_timestamp:
            date_match_iso = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).isoformat()

        match_data = {
            "external_id": str(match['id']),
            "statut": match.get('status', {}).get('type', 'scheduled'),
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "date_match": date_match_iso,
            "score_dom": match.get('homeScore', {}).get('current', 0) or 0,
            "score_ext": match.get('awayScore', {}).get('current', 0) or 0
        }
        all_matches.append(match_data)
    
    # Upsert en masse des matchs
    if all_matches:
        supabase.table("Matchs").upsert(all_matches, on_conflict="external_id").execute()
        print(f"{len(all_matches)} matchs mis à jour/ajoutés au calendrier.")

if __name__ == "__main__":
    run_calendar()
