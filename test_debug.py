import os
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Tentative de connexion à Supabase...")

try:
    today_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Test de lecture
    res = supabase.table("Configuration").select("*").eq("id", "default_config").execute()
    print("Lecture réussie, données actuelles :", res.data)
    
    current_count = 0
    current_logs = []
    
    if res.data:
        current_count = res.data[0].get("api_request_count", 0) or 0
        current_logs = res.data[0].get("api_request_logs", []) or []
    
    new_count = current_count + 1
    current_logs.insert(0, f"[{timestamp}] Test Debug Manuel")
    
    # Test d'écriture / upsert
    response_upsert = supabase.table("Configuration").upsert({
        "id": "default_config",
        "api_request_count": new_count,
        "last_reset_date": today_str,
        "api_request_logs": current_logs
    }, on_conflict="id").execute()
    
    print("Écriture (upsert) réussie !", response_upsert.data)

except Exception as e:
    print("ERREUR CRITIQUE DÉTECTÉE :", e)
