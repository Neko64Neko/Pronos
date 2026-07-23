import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

print("--- LE SCRIPT LIVE COMMENCE ---")

# Récupération automatique depuis les secrets GitHub
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_update():
    # 1. Vérification intelligente dans Supabase avant d'appeler l'API
    now = datetime.now(timezone.utc)
    
    try:
        response_db = supabase.table("Matchs").select("*").execute()
        matches_db = response_db.data
        
        match_en_cours = False
        if matches_db:
            for m in matches_db:
                if m.get('date_match') and m.get('statut') != 'finished':
                    match_time_str = m['date_match']
                    match_time = datetime.fromisoformat(match_time_str.replace('Z', '+00:00'))
                    
                    # Fenêtre active : Le match a commencé il y a moins de 100 minutes
                    if match_time <= now <= match_time + timedelta(minutes=100):
                        match_en_cours = True
                        break
        
        # Si aucun match n'est dans sa fenêtre, on stoppe (0 requête consommée)
        if not match_en_cours:
            print("Aucun match actif dans la fenêtre des 100 minutes. Arrêt du script (0 requête API consommée).")
            return
            
    except Exception as e:
        print(f"Erreur lors de la vérification de la fenêtre active : {e}")

    # 2. Appel de l'API Live (uniquement si un match est en cours)
    url = "https://rugbyapi2.p.rapidapi.com/api/rugby/matches/live"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    print("Appel de l'API Live...")
    response = requests.get(url, headers=headers)
    print(f"Réponse API Live reçue avec le code statut : {response.status_code}")

    # 3. --- MISE À JOUR DU COMPTEUR API DANS SUPABASE ---
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
            current_logs.insert(0, f"[{timestamp}] MAJ Live (Automatique)")
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

    # 4. Traitement des données reçues de l'API Live
    data = response.json()
    events = data.get('events', [])

    if not events:
        print("Aucun match trouvé sur l'API Live.")
        return

    for match in events:
        if str(match.get('tournament', {}).get('id')) != "420":
            continue 
            
        match_data = {
            "external_id": match['id'],
            "statut": match['status']['type'],
            "equipe_dom": match['homeTeam']['name'],
            "equipe_ext": match['awayTeam']['name'],
            "score_dom": match['homeScore']['current'],
            "score_ext": match['awayScore']['current']
        }
        
        supabase.table("Matchs").upsert([match_data], on_conflict="external_id").execute()
        print(f"Match mis à jour : {match['homeTeam']['name']} vs {match['awayTeam']['name']}")

if __name__ == "__main__":
    run_update()
