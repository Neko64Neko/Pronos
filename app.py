import streamlit as st
from supabase import create_client
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import random
import extra_streamlit_components as stx
from streamlit_autorefresh import st_autorefresh

# CONFIGURATION DE LA PAGE
st.set_page_config(page_title="Pronos Top 14", page_icon="🏉", layout="centered")

# 1. CONNEXION À SUPABASE
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# Gestionnaire de cookies
cookie_manager = stx.CookieManager()

# =====================================================================
# SYSTEME DE SCRAPING GRATUIT ET AUTOMATIQUE
# =====================================================================

def verifier_et_importer_matchs():
    """Version robuste : scanne L'Équipe et dynamiquement TheSportsDB selon la saison en cours."""
    matchs_traites = 0
    url_scraping = "https://www.lequipe.fr/Rugby/Top-14/page-calendrier-resultats"
    
    # 1. Tentative via le scraping L'Équipe
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url_scraping, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            blocs_matchs = soup.find_all('div', class_='Match_match__')
            for bloc in blocs_matchs:
                try:
                    eq_dom = bloc.find('span', class_='team-home').text.strip()
                    eq_ext = bloc.find('span', class_='team-away').text.strip()
                    score_txt = bloc.find('span', class_='score').text.strip()
                    
                    statut = "FT" if "-" in score_txt else "NS"
                    sc_dom, sc_ext = map(int, score_txt.split("-")) if "-"
