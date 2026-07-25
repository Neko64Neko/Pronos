import os
from datetime import datetime, timezone
import requests
from supabase import create_client

def get_secret(key):
    """Récupère un secret depuis os.environ ou st.secrets de manière transparente"""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return None

def peupler_table_equipes_automatiquement(events_api, supabase): 
    """
    Parcourt la liste des événements de l'API, extrait les équipes uniques 
    et les insère dans la table 'Equipes' de Supabase.
    """
    equipes_collectees = {}

    for event in events_api:
        for type_equipe in ['homeTeam', 'awayTeam']:
            team_data = event.get(type_equipe)
            if team_data:
                team_id = team_data.get('id')
                team_name = team_data.get('name')
                
                if team_id and team_name:
                    if team_id not in equipes_collectees:
                        logo_url = f"https://api.sofascore.com/api/v1/team/{team_id}/image"
                        equipes_collectees[team_id] = {
                            "id": team_id,
                            "nom": team_name,
                            "logo_url": logo_url
                        }

    nb_ajoutes = 0
    for team_id, data in equipes_collectees.items():
        try:
            supabase.table("Equipes").upsert(data).execute()
            nb_ajoutes += 1
        except Exception as e:
            print(f"Erreur pour l'équipe {data['nom']} : {e}")

    return nb_ajoutes

def run_calendar():
    print("--- LE SCRIPT CALENDRIER COMMENCE ---")
    
    SUPABASE_URL = get_secret("SUPABASE_URL")
    SUPABASE_KEY = get_secret("SUPABASE_KEY")
    RAPIDAPI_KEY = get_secret("RAPIDAPI_KEY")

    if not SUPABASE_URL or not SUPABASE_KEY or not RAPIDAPI_KEY:
        print("ERREUR : Il manque un ou plusieurs secrets (Vérifiez les secrets GitHub ou Streamlit).")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    tournament_id = "420"
    season_id = "98426"
    
    url = f"https://rugbyapi2.p.rapidapi.com/api/rugby/tournament/{tournament_id}/season/{season_id}/matches/next/0"
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
    }
    
    print("Appel de l'API RapidAPI en cours...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except Exception as e:
        print(f"ERREUR RÉSEAU LORS DE L'APPEL API : {e}")
        return

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
            current_logs.insert(0, f"[{timestamp}] MAJ Calendrier (Admin App)")
            if len(current_logs) > 20:
                current_logs = current_logs[:20]
                
            supabase.table("Configuration").update({
                "api_request_count": new_count,
                "last_reset_date": today_str,
                "api_request_logs": current_logs
            }).eq("id", target_id).execute()
            
            print(f"SUCCÈS : Compteur API mis à jour à {new_count} requêtes aujourd'hui.")
    except Exception as e_config:
        print(f"ERREUR LORS DE LA MAJ DU COMPTEUR : {e_config}")

    if response.status_code == 204:
        print("API connectée avec succès, mais aucun match à venir (204).")
        return
        
    try:
        data = response.json()
    except Exception as e:
        print(f"ERREUR : Impossible de parser le JSON : {e}")
        return

    events = data if isinstance(data, list) else data.get('events', [])

    if not events:
        print("Aucun match à venir trouvé dans les données.")
        return

    # --- REMPLISSAGE AUTOMATIQUE DES ÉQUIPES DANS SUPABASE --- 1 FOIS ---
    # nb = peupler_table_equipes_automatiquement(events, supabase)
    # print(f"SUCCÈS : {nb} équipes ont été synchronisées dans Supabase !")

    all_matches = []
    for match in events:
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
    
    if all_matches:
        try:
            supabase.table("Matchs").upsert(all_matches, on_conflict="external_id").execute()
            print(f"SUCCÈS : {len(all_matches)} matchs insérés/mis à jour dans Supabase.")
        except Exception as e_upsert:
            print(f"ERREUR LORS DE L'INSERTION SUPABASE : {e_upsert}")

if __name__ == "__main__":
    run_calendar()
