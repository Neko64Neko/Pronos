import requests
from bs4 import BeautifulSoup

def verifier_et_importer_matchs():
    """Scrape le calendrier de L'Équipe."""
    matchs_traites = 0
    url_scraping = "https://www.lequipe.fr/Rugby/Top-14/page-calendrier-resultats"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
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
                    sc_dom, sc_ext = map(int, score_txt.split("-")) if "-" in score_txt else (None, None)
                    if "En cours" in bloc.text or "Direct" in bloc.text: statut = "LIVE"
                    
                    match_id = abs(hash(f"{eq_dom}_{eq_ext}")) % 10000000
                    supabase.table("Matchs").upsert({
                        "id": match_id, "equipe_dom": eq_dom, "equipe_ext": eq_ext,
                        "date_match": (datetime.utcnow() + timedelta(days=2)).isoformat(),
                        "score_dom": sc_dom, "score_ext": sc_ext, "statut": statut
                    }).execute()
                    matchs_traites += 1
                except Exception: continue
    except Exception: pass

    # 2. Sécurité TheSportsDB - CALCUL DYNAMIQUE DE LA SAISON
    if matchs_traites == 0:
        maintenant = datetime.now()
        annee_saison_courante = maintenant.year - 1 if maintenant.month < 8 else maintenant.year
        annees_a_tester = [str(annee_saison_courante - 1), str(annee_saison_courante)]
        
        for annee in annees_a_tester:
            try:
                url_tsdb = f"https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=4413&s={annee}"
                res = requests.get(url_tsdb, timeout=10).json()
                if res.get("events"):
                    for event in res["events"]:
                        m_id = int(event["idEvent"])
                        statut = "LIVE" if event.get("strProgress") == "In Progress" else ("FT" if event.get("strStatus") == "Match Finished" else "NS")
                        
                        if event["intHomeScore"] is None:
                            date_match = (datetime.utcnow() + timedelta(days=5)).isoformat()
                        else:
                            date_match = f"{event['dateEvent']}T{event['strTime']}" if event.get('strTime') else datetime.utcnow().isoformat()

                        supabase.table("Matchs").upsert({
                            "id": m_id, "equipe_dom": event["strHomeTeam"], "equipe_ext": event["strAwayTeam"],
                            "date_match": date_match,
                            "score_dom": int(event["intHomeScore"]) if event["intHomeScore"] is not None else None,
                            "score_ext": int(event["intAwayScore"]) if event["intAwayScore"] is not None else None,
                            "statut": statut
                        }).execute()
                        matchs_traites += 1
            except Exception: pass
            
    return matchs_traites
    except Exception as e:
        print(f"Erreur de scraping : {e}")
        return 0
