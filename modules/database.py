import streamlit as st
from supabase import create_client

# Initialisation du client Supabase
# On utilise st.secrets pour la sécurité
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def reset_saison():
    """Réinitialise toutes les tables de la base de données."""
    try:
        supabase.table("Pronostics").delete().not_.is_("id", "null").execute()
        supabase.table("Réponses_Questions").delete().not_.is_("id", "null").execute()
        supabase.table("Matchs").delete().not_.is_("id", "null").execute()
        supabase.table("Questions_Bonus").delete().not_.is_("id", "null").execute()
        supabase.table("Joueurs").update({"score": 0}).not_.is_("id", "null").execute()
        return True
    except Exception as e:
        return str(e)
