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
    """Version force brute : scanne L'Équipe et TheSportsDB sur plusieurs années."""
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
                    sc_dom, sc_ext = map(int, score_txt.split("-")) if "-" in score_txt else (None, None)
                    if "En cours" in bloc.text or "Direct" in bloc.text: statut = "LIVE"
                    
                    match_id = abs(hash(f"{eq_dom}_{eq_ext}")) % 10000000
                    supabase.table("Matchs").upsert({
                        "id": match_id, "equipe_dom": eq_dom, "equipe_ext": eq_ext,
                        "date_match": (datetime.utcnow() + timedelta(days=2)).isoformat(), # Date forcée dans le futur pour le prono
                        "score_dom": sc_dom, "score_ext": sc_ext, "statut": statut
                    }).execute()
                    matchs_traites += 1
                except Exception: continue
    except Exception: pass

    # 2. Sécurité TheSportsDB : On teste 2025 ET 2026 pour être sûr de capter la finale
    if matchs_traites == 0:
        for annee in ["2025", "2026"]:
            try:
                url_tsdb = f"https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=4413&s={annee}"
                res = requests.get(url_tsdb, timeout=10).json()
                if res.get("events"):
                    for event in res["events"]:
                        # On cherche spécifiquement si c'est un match de phase finale ou si les scores sont vides
                        m_id = int(event["idEvent"])
                        statut = "LIVE" if event.get("strProgress") == "In Progress" else ("FT" if event.get("strStatus") == "Match Finished" else "NS")
                        
                        # FORCE DATE FUTURE : Si le match n'a pas encore de score, on le pousse artificiellement dans le futur 
                        # pour contourner le filtre d'affichage Streamlit
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


def sauvegarder_prono_auto(match_id, equipe_dom, equipe_ext, user_id_cible):
    """Sauvegarde instantanément le pronostic dès qu'un élément change."""
    vrai_nom_gagnant = st.session_state.get(f"w_{match_id}")
    ecart = st.session_state.get(f"m_{match_id}")
    
    if vrai_nom_gagnant == "..." or ecart == "...":
        return

    val_gagnant = "home" if vrai_nom_gagnant == equipe_dom else ("away" if vrai_nom_gagnant == equipe_ext else "draw")
    prono_existant = supabase.table("Pronostics").select("id").eq("user_id", user_id_cible).eq("match_id", match_id).execute().data
    
    donnees_prono = {
        "user_id": user_id_cible, "match_id": match_id, "gagnant_prevu": val_gagnant, "ecart_prevu": ecart
    }
    
    try:
        if prono_existant:
            supabase.table("Pronostics").update(donnees_prono).eq("id", prono_existant[0]["id"]).execute()
        else:
            supabase.table("Pronostics").insert(donnees_prono).execute()
    except Exception as e:
        st.error(f"Erreur sauvegarde automatique : {e}")


def sauvegarder_bonus_auto(question_id, user_id_cible):
    """Sauvegarde instantanément la réponse à une question bonus."""
    choix = st.session_state.get(f"bonus_q_{question_id}")
    if choix == "...":
        return
        
    deja_repondu = supabase.table("Réponses_Questions").select("id").eq("user_id", user_id_cible).eq("question_id", question_id).execute().data
    data_pb = {"user_id": user_id_cible, "question_id": question_id, "reponse_joueur": choix}
    
    try:
        if deja_repondu:
            supabase.table("Réponses_Questions").update(data_pb).eq("id", deja_repondu[0]['id']).execute()
        else:
            supabase.table("Réponses_Questions").insert(data_pb).execute()
    except Exception as e:
        st.error(f"Erreur sauvegarde bonus : {e}")

# =====================================================================
# INITIALISATION ET GESTION DU REFRESH DYNAMIQUE (5 MIN)
# =====================================================================
if "user_id" not in st.session_state: st.session_state.user_id = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "pseudo" not in st.session_state: st.session_state.pseudo = ""

TRANCHES_ECARTS = ["1-6", "7-10", "11-15", "16-20", "21-30", "31-40", "41-50", "51+"]
maintenant_paris = datetime.utcnow() + timedelta(hours=2)

# REFRESH AUTOMATIQUE INTELLIGENT
# On vérifie en BDD si au moins un match possède le statut "LIVE"
try:
    matchs_en_direct = supabase.table("Matchs").select("id").eq("statut", "LIVE").execute().data
    if matchs_en_direct:
        # Un match est en cours : on force Streamlit à se recharger toutes les 5 minutes (300000 ms)
        # Cela déclenche l'exécution du script complet et met à jour les scores scrapés
        st_autorefresh(interval=300000, key="live_rugby_refresh")
        verifier_et_importer_matchs() # Exécute le scraping en tâche de fond
except Exception:
    pass

# --- tentative de reconnexion via COOKIE ---
if st.session_state.user_id is None:
    saved_user_id = cookie_manager.get(cookie="top14_user_id")
    if saved_user_id:
        try:
            profil = supabase.table("Joueurs").select("*").eq("id", saved_user_id).single().execute()
            if profil.data:
                st.session_state.user_id = saved_user_id
                st.session_state.is_admin = profil.data["is_admin"]
                st.session_state.pseudo = profil.data["pseudo"]
                st.rerun()
        except Exception:
            pass

# ---- CONNEXION / INSCRIPTION / MDP OUBLIÉ ----
if st.session_state.user_id is None:
    st.title("🏉 Pronos Top 14")
    onglet = st.tabs(["Se connecter", "S'inscrire", "Mot de passe oublié"])
    
    with onglet[0]:
        mail = st.text_input("Email", key="login_email")
        mdp = st.text_input("Mot de passe", type="password", key="login_pass")
        if st.button("Connexion"):
            try:
                res = supabase.auth.sign_in_with_password({"email": mail, "password": mdp})
                profil = supabase.table("Joueurs").select("*").eq("id", res.user.id).single().execute()
                
                st.session_state.user_id = res.user.id
                st.session_state.is_admin = profil.data["is_admin"]
                st.session_state.pseudo = profil.data["pseudo"]
                
                cookie_manager.set("top14_user_id", res.user.id, max_age=2592000)
                st.success(f"Ravi de vous revoir {st.session_state.pseudo} !")
                time.sleep(0.5)
                st.rerun()
            except Exception: st.error("Identifiants incorrects.")

    with onglet[1]:
        new_mail = st.text_input("Email", key="reg_email")
        new_mdp = st.text_input("Mot de passe", type="password", key="reg_pass")
        pseudo = st.text_input("Pseudo")
        if st.button("Créer mon compte"):
            if len(pseudo) < 3: st.error("Pseudo trop court !")
            else:
                try:
                    res = supabase.auth.sign_up({"email": new_mail, "password": new_mdp})
                    supabase.table("Joueurs").insert({"id": res.user.id, "pseudo": pseudo, "email": new_mail, "score": 0, "is_admin": False}).execute()
                    st.success("Compte créé avec succès !")
                except Exception as e: st.error(f"Erreur : {e}")

    with onglet[2]:
        st.subheader("Réinitialiser mon mot de passe")
        reset_email = st.text_input("Entrez votre adresse email de connexion", key="reset_mail")
        if st.button("Envoyer le lien de récupération"):
            if reset_email:
                try:
                    supabase.auth.reset_password_for_email(reset_email)
                    st.success("✉️ Si ce compte existe, un email de réinitialisation vous a été envoyé !")
                except Exception as e: st.error(f"Erreur : {e}")
            else: st.warning("Veuillez renseigner votre adresse email.")

# ---- APPLICATION CONNECTÉE ----
else:
    col_user, col_logout = st.columns([4, 1])
    with col_user:
        st.markdown(f"👤 Connecté en tant que **{st.session_state.pseudo}**")
    with col_logout:
        if st.button("Déconnexion 🚪", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state.user_id = None
            cookie_manager.delete("top14_user_id")
            st.rerun()

    st.markdown("---")

    liste_onglets = ["🏆 Classement", "✍️ Faire mes Pronostics", "📊 Résultats & Direct"]
    if st.session_state.is_admin:
        liste_onglets.append("⚙️ Administration")
        
    onglets_principaux = st.tabs(liste_onglets)

    try:
        conf = supabase.table("Configuration").select("*").eq("id", "default_config").single().execute().data
        pts_gagnant_cfg = conf.get("pts_gagnant", 3) if conf else 3
        pts_ecart_cfg = conf.get("pts_ecart", 2) if conf else 2
        seuil_ose_cfg = conf.get("seuil_poursentage_ose", 20) if conf else 20
        mult_ose_cfg = conf.get("multiplicateur_ose", 2) if conf else 2
    except Exception:
        pts_gagnant_cfg, pts_ecart_cfg, seuil_ose_cfg, mult_ose_cfg = 3, 2, 20, 2

    pts_parfait_cfg = pts_gagnant_cfg + pts_ecart_cfg

    # =====================================================================
    # ONGLET 1 : CLASSEMENT
    # =====================================================================
    with onglets_principaux[0]:
        st.title("🏆 Classement Général")
        try:
            joueurs = supabase.table("Joueurs").select("pseudo, score").order("score", desc=True).execute()
            if joueurs.data: st.table(joueurs.data)
            else: st.info("Aucun joueur pour le moment.")
        except Exception as e: st.error(f"Erreur : {e}")

    # =====================================================================
    # ONGLET 2 : FAIRE MES PRONOSTICS
    # =====================================================================
    with onglets_principaux[1]:
        st.title("✍️ Saisir les Pronostics")

        id_joueur_cible = st.session_state.user_id
        if st.session_state.is_admin:
            try:
                liste_membres = supabase.table("Joueurs").select("id, pseudo").order("pseudo").execute().data
                if liste_membres:
                    index_admin = 0
                    for idx, m in enumerate(liste_membres):
                        if m['id'] == st.session_state.user_id:
                            index_admin = idx
                            break
                    st.warning("🛠️ **Mode Admin actif** : Vous pouvez pronostiquer à la place d'un autre joueur.")
                    choix_membre = st.selectbox("Sélectionner le compte joueur à utiliser :", options=liste_membres, format_func=lambda x: x['pseudo'], index=index_admin)
                    if choix_membre: id_joueur_cible = choix_membre['id']
            except Exception as e: st.error(f"Erreur récupération membres : {e}")

        # --- QUESTIONS BONUS ---
        st.subheader("🎯 Questions Bonus du moment")
        try:
            questions = supabase.table("Questions_Bonus").select("*").eq("statut", "En cours").order("date_limite").execute().data
            questions_ouvertes = []
            if questions:
                for q in questions:
                    date_limite_brute = q['date_limite'].split("+")[0].split("Z")[0]
                    date_limite_obj = datetime.fromisoformat(date_limite_brute)
                    if maintenant_paris <= date_limite_obj: questions_ouvertes.append((q, date_limite_obj))
            
            if questions_ouvertes:
                for q, date_limite_obj in questions_ouvertes:
                    st.markdown(f"**{q['question']}** *(Rapporte : {q.get('points', 5)} pts)*")
                    options_rep = ["..."] + ([opt.strip() for opt in q['choix_reponse'].split("/")] if q['choix_reponse'] else ["Oui", "Non"])
                    deja_repondu = supabase.table("Réponses_Questions").select("*").eq("user_id", id_joueur_cible).eq("question_id", q['id']).execute().data
                    
                    index_defaut = 0
                    if deja_repondu and deja_repondu[0]['reponse_joueur'] in options_rep:
                        index_defaut = options_rep.index(deja_repondu[0]['reponse_joueur'])
                    
                    st.radio("Ta réponse :", options=options_rep, index=index_defaut, key=f"bonus_q_{q['id']}", on_change=sauvegarder_bonus_auto, args=(q['id'], id_joueur_cible))
                    if deja_repondu: st.caption("✅ _Enregistré automatiquement_")
                    st.markdown("---")
            else: st.write("Aucune question bonus ouverte actuellement.")
        except Exception as e: st.error(f"Erreur questions bonus : {e}")

        # --- MATCHS OUVERTS ---
        st.subheader("🏉 Matchs ouverts du Top 14")
        try:
            matchs = supabase.table("Matchs").select("*").order("date_match").execute().data
            matchs_ouverts = []
            if matchs:
                for m in matchs:
                    date_m_brute = m['date_match'].split("+")[0].split("Z")[0]
                    date_m_obj = datetime.fromisoformat(date_m_brute)
                    if maintenant_paris < date_m_obj: matchs_ouverts.append(m)
            
            if matchs_ouverts:
                for m in matchs_ouverts:
                    st.write(f"### {m['equipe_dom']} vs {m['equipe_ext']}")
                    prono_existant = supabase.table("Pronostics").select("*").eq("user_id", id_joueur_cible).eq("match_id", m['id']).execute().data
                    
                    liste_vainqueurs = ["...", m['equipe_dom'], m['equipe_ext'], "Match Nul"]
                    liste_ecarts = ["..."] + TRANCHES_ECARTS
                    
                    def_winner_idx, def_margin_idx = 0, 0
                    if prono_existant:
                        pe = prono_existant[0]
                        winner_name = m['equipe_dom'] if pe['gagnant_prevu'] == 'home' else (m['equipe_ext'] if pe['gagnant_prevu'] == 'away' else "Match Nul")
                        if winner_name in liste_vainqueurs: def_winner_idx = liste_vainqueurs.index(winner_name)
                        if pe.get('ecart_prevu') in liste_ecarts: def_margin_idx = liste_ecarts.index(pe.get('ecart_prevu'))

                    st.radio("Vainqueur ?", liste_vainqueurs, index=def_winner_idx, key=f"w_{m['id']}", on_change=sauvegarder_prono_auto, args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible))
                    st.selectbox("Écart ?", liste_ecarts, index=def_margin_idx, key=f"m_{m['id']}", on_change=sauvegarder_prono_auto, args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible))
                    if prono_existant: st.caption("✅ _Pronostic enregistré automatiquement_")
                    st.markdown("---")
            else: st.info("Aucun match ouvert aux pronostics pour l'instant.")
        except Exception as e: st.error(f"Erreur match : {e}")

    # =====================================================================
    # ONGLET 3 : RÉSULTATS & DIRECT (MIS À JOUR TOUTES LES 5 MIN SI LIVE)
    # =====================================================================
    with onglets_principaux[2]:
        st.title("📊 Résultats & Direct")
        if matchs_en_direct:
            st.success("⚡ **Mode Direct Actif** : Les scores se rafraîchissent automatiquement toutes les 5 minutes.")
            
        st.subheader("🏉 Matchs Clos / En cours")
        try:
            matchs = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
            matchs_clos = []
            if matchs:
                for m in matchs:
                    date_m_brute = m['date_match'].split("+")[0].split("Z")[0]
                    date_m_obj = datetime.fromisoformat(date_m_brute)
                    if maintenant_paris >= date_m_obj: matchs_clos.append(m)
            
            if matchs_clos:
                for m in matchs_clos:
                    sc_dom = m['score_dom'] if m['score_dom'] is not None else 0
                    sc_ext = m['score_ext'] if m['score_ext'] is not None else 0
                    
                    label_live = "🔴 [EN DIRECT]" if m['statut'] == 'LIVE' else ""
                    st.write(f"### {m['equipe_dom']} {sc_dom} - {sc_ext} {m['equipe_ext']}  {label_live}")
                    
                    with st.expander("👁️ Voir les pronostics en direct"):
                        all_pronos = supabase.table("Pronostics").select("gagnant_prevu, ecart_prevu, Joueurs(pseudo)").eq("match_id", m['id']).execute().data
                        if all_pronos:
                            vrai_gagnant_brut = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                            for p in all_pronos:
                                pseudo_j = p.get('Joueurs', {}).get('pseudo', 'Inconnu')
                                nom_prevu = m['equipe_dom'] if p['gagnant_prevu'] == 'home' else (m['equipe_ext'] if p['gagnant_prevu'] == 'away' else "Match Nul")
                                st.markdown(f"👤 **{pseudo_j}** : {nom_prevu} ({p['ecart_prevu']})")
                        else: st.write("Aucun prono enregistré.")
                    st.markdown("---")
            else: st.info("Aucun match n'a encore débuté.")
        except Exception as e: st.error(f"Erreur matchs clos : {e}")

    # =====================================================================
    # ONGLET 4 : PANEL ADMINISTRATION
    # =====================================================================
    if st.session_state.is_admin:
        with onglets_principaux[3]:
            st.title("⚙️ Console d'Administration Privée")
            
            # ICI : Ajout du 5ème onglet dans la liste
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "🎯 Configuration", 
                "➕ Matchs Manuels", 
                "🎁 Questions Bonus", 
                "🔄 Synchro Scraping",
                "🚨 Changement de Saison"
            ])
            
            # --- TAB 1 : CONFIGURATION ---
            with tab1:
                st.subheader("🎛️ Configuration du Barème")
                try:
                    current_config = supabase.table("Configuration").select("*").eq("id", "default_config").single().execute().data
                except Exception:
                    current_config = {}
                
                with st.form("form_points"):
                    val_gagnant = st.number_input("Points pour le bon vainqueur", value=current_config.get("pts_gagnant", 3) if current_config else 3)
                    val_ecart = st.number_input("Points pour le bon écart", value=current_config.get("pts_ecart", 2) if current_config else 2)
                    val_seuil = st.number_input("Seuil de déclenchement du mode Osé (en %)", value=current_config.get("seuil_poursentage_ose", 20) if current_config else 20)
                    val_mult = st.number_input("Multiplicateur Osé (ex: 2)", value=current_config.get("multiplicateur_ose", 2) if current_config else 2)
                    
                    if st.form_submit_button("💾 Sauvegarder"):
                        supabase.table("Configuration").upsert({
                            "id": "default_config", "pts_gagnant": val_gagnant, "pts_ecart": val_ecart, 
                            "seuil_poursentage_ose": val_seuil, "multiplicateur_ose": val_mult
                        }).execute()
                        st.success("Barème enregistré !")
                        st.rerun()

            # --- TAB 2 : MATCHS MANUELS & SCORES ---
            with tab2:
                st.subheader("➕ Ajouter un Match manuellement")
                with st.form("form_ajout_match"):
                    eq_dom = st.text_input("Équipe Domicile")
                    eq_ext = st.text_input("Équipe Extérieur")
                    date_c = st.date_input("Date")
                    heure_c = st.time_input("Heure")
                    if st.form_submit_button("➕ Créer le match"):
                        if eq_dom and eq_ext:
                            dt_combine = datetime.combine(date_c, heure_c).isoformat()
                            id_m = int(datetime.timestamp(datetime.combine(date_c, heure_c))) + random.randint(1, 1000)
                            supabase.table("Matchs").insert({
                                "id": id_m, "equipe_dom": eq_dom, "equipe_ext": eq_ext, "date_match": dt_combine, "score_dom": None, "score_ext": None, "statut": "NS"
                            }).execute()
                            st.success("Match créé de force !")
                            st.rerun()
                
                st.markdown("---")
                st.subheader("📝 Saisir le résultat d'un match (Manuel)")
                try:
                    tous_matchs = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
                    if tous_matchs:
                        def format_match_choice(m):
                            sc_d = m['score_dom'] if m['score_dom'] is not None else "?"
                            sc_e = m['score_ext'] if m['score_ext'] is not None else "?"
                            return f"{m['equipe_dom']} ({sc_d}) vs ({sc_e}) {m['equipe_ext']} - [{m['statut']}]"
                        
                        match_selectionne = st.selectbox("Sélectionner le match à mettre à jour :", options=tous_matchs, format_func=format_match_choice)
                        
                        if match_selectionne:
                            with st.form(f"form_score_manual_{match_selectionne['id']}"):
                                col_sc1, col_sc2 = st.columns(2)
                                with col_sc1:
                                    nouveau_score_dom = st.number_input(f"Score {match_selectionne['equipe_dom']}", min_value=0, value=match_selectionne['score_dom'] if match_selectionne['score_dom'] is not None else 0, step=1)
                                with col_sc2:
                                    nouveau_score_ext = st.number_input(f"Score {match_selectionne['equipe_ext']}", min_value=0, value=match_selectionne['score_ext'] if match_selectionne['score_ext'] is not None else 0, step=1)
                                
                                liste_statuts = ["NS", "FT", "LIVE"]
                                statut_index = liste_statuts.index(match_selectionne['statut']) if match_selectionne['statut'] in liste_statuts else 1
                                nouveau_statut = st.selectbox("Statut du match", options=liste_statuts, index=statut_index)
                                
                                if st.form_submit_button("💾 Enregistrer le résultat"):
                                    supabase.table("Matchs").update({
                                        "score_dom": nouveau_score_dom, "score_ext": nouveau_score_ext, "statut": nouveau_statut
                                    }).eq("id", match_selectionne['id']).execute()
                                    st.success("Résultat mis à jour !")
                                    time.sleep(0.5)
                                    st.rerun()
                    else:
                        st.info("Aucun match disponible.")
                except Exception as e: st.error(f"Erreur : {e}")

            # --- TAB 3 : QUESTIONS BONUS ---
            with tab3:
                st.subheader("📝 Créer une Question Bonus")
                with st.form("form_bonus"):
                    intitule = st.text_input("Intitulé de la question")
                    choix = st.text_input("Choix possibles (séparés par un slash)", value="Oui / Non")
                    pts_bonus = st.number_input("Points accordés", min_value=1, value=5)
                    d_limite = st.date_input("Date limite")
                    h_limite = st.time_input("Heure limite")
                    
                    if st.form_submit_button("🚀 Publier"):
                        if intitule:
                            dt_lim_combine = datetime.combine(d_limite, h_limite).isoformat()
                            supabase.table("Questions_Bonus").insert({
                                "question": intitule, "choix_reponse": choix, "date_limite": dt_lim_combine, "statut": "En cours", "points": pts_bonus
                            }).execute()
                            st.success("Question bonus en ligne !")
                            st.rerun()
                
                st.markdown("---")
                st.subheader("✅ Corriger et Valider une question bonus")
                q_ouvertes = supabase.table("Questions_Bonus").select("*").eq("statut", "En cours").execute().data
                if q_ouvertes:
                    q_choisie = st.selectbox("Sélectionner la question :", options=q_ouvertes, format_func=lambda x: f"{x['question']} ({x.get('points', 5)} pts)")
                    options_validation = [opt.strip() for opt in q_choisie['choix_reponse'].split("/")] if q_choisie['choix_reponse'] else ["Oui", "Non"]
                    bonne_rep = st.radio("Bonne réponse :", options=options_validation)
                    
                    if st.button("Clôturer et distribuer les points"):
                        points_a_gagner = q_choisie.get('points', 5)
                        reponses_joueurs = supabase.table("Réponses_Questions").select("user_id, reponse_joueur").eq("question_id", q_choisie['id']).execute().data
                        
                        compteur_gagnants = 0
                        if reponses_joueurs:
                            for r in reponses_joueurs:
                                if r['reponse_joueur'].strip() == bonne_rep.strip():
                                    joueur_data = supabase.table("Joueurs").select("score").eq("id", r['user_id']).single().execute().data
                                    if joueur_data:
                                        nouveau_score = joueur_data.get('score', 0) + points_a_gagner
                                        supabase.table("Joueurs").update({"score": nouveau_score}).eq("id", r['user_id']).execute()
                                        compteur_gagnants += 1
                        
                        supabase.table("Questions_Bonus").update({"reponse_valide": bonne_rep, "statut": "Validé"}).eq("id", q_choisie['id']).execute()
                        st.success(f"🎉 Validé ! {compteur_gagnants} joueur(s) récompensés.")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                else:
                    st.write("Aucune question en cours de validation.")

            # --- TAB 4 : SYNCHRO SCRAPING ---
            with tab4:
                st.subheader("🔄 Lanceur de Scraping Manuel")
                st.write("Le système se met à jour tout seul pendant les matchs, mais tu peux forcer un scan global ici.")
                if st.button("⚡ Lancer la Synchronisation"):
                    with st.spinner("Scraping en cours..."):
                        nb = verifier_et_importer_matchs()
                        st.success(f"Terminé ! {nb} matchs traités avec succès via la méthode gratuite.")
                        st.rerun()

            # --- TAB 5 : CHANGEMENT DE SAISON (RETROUVÉ !) ---
            with tab5:
                st.subheader("🚨 Zone de Danger : Reset de fin de Saison")
                st.error("⚠️ Attention : Cette action va effacer définitivement tous les matchs, pronostics et questions bonus de la base de données Supabase. Les profils des joueurs seront conservés mais leurs scores repasseront à 0.")
                
                confirmation_secu = st.checkbox("Je confirme vouloir tout réinitialiser pour la nouvelle saison.", key="danger_zone_confirm")
                
                if st.button("🔥 Réinitialiser l'application pour la nouvelle saison", type="primary", disabled=not confirmation_secu):
                    with st.spinner("Nettoyage complet de la base de données..."):
                        try:
                            # Purge complète des tables liées à la saison passée
                            supabase.table("Pronostics").delete().not_.is_("id", "null").execute()
                            supabase.table("Réponses_Questions").delete().not_.is_("id", "null").execute()
                            supabase.table("Matchs").delete().not_.is_("id", "null").execute()
                            supabase.table("Questions_Bonus").delete().not_.is_("id", "null").execute()
                            # Remise à zéro des scores mais conservation des utilisateurs
                            supabase.table("Joueurs").update({"score": 0}).not_.is_("id", "null").execute()
                            
                            st.success("🎉 L'application a été nettoyée avec succès pour la prochaine saison !")
                            st.balloons()
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Une erreur est survenue lors du reset : {e}")
