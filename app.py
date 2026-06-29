import streamlit as st
from supabase import create_client
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import random
import extra_streamlit_components as stx
from streamlit_autorefresh import st_autorefresh

# 1 - PARAMETRES ET CONNEXION
# 1.1 - CONFIGURATION DE LA PAGE
st.set_page_config(page_title="Pronos Top 14", page_icon="🏉", layout="centered")

# 1.2 - CONNEXION À SUPABASE
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1.3 - Gestionnaire de cookies
cookie_manager = stx.CookieManager()

# =====================================================================
# 2 - SYSTEME DE SCRAPING GRATUIT ET AUTOMATIQUE
# =====================================================================

def verifier_et_importer_matchs():
    """Version robuste : scanne L'Équipe et dynamiquement TheSportsDB selon la saison en cours."""
    matchs_traites = 0
    url_scraping = "https://www.lequipe.fr/Rugby/Top-14/page-calendrier-resultats"
    
    # 2.1 - Tentative via le scraping L'Équipe
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
                        "date_match": (datetime.utcnow() + timedelta(days=2)).isoformat(),
                        "score_dom": sc_dom, "score_ext": sc_ext, "statut": statut
                    }).execute()
                    matchs_traites += 1
                except Exception: continue
    except Exception: pass

    # 2.2 - Sécurité TheSportsDB - CALCUL DYNAMIQUE DE LA SAISON
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
    
#2.3 - SAUVEGARDE AUTO PRONO
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
        
#2.4 - Sauvegarde Bonus AUTO
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
# 3 - INITIALISATION ET GESTION DE LA SESSION
# =====================================================================
if "user_id" not in st.session_state: st.session_state.user_id = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "pseudo" not in st.session_state: st.session_state.pseudo = ""
if "onglet_actif" not in st.session_state: st.session_state.onglet_actif = "📊"

TRANCHES_ECARTS = ["1-6", "7-10", "11-15", "16-20", "21-30", "31-40", "41-50", "51+"]
maintenant_paris = datetime.utcnow() + timedelta(hours=2)

# 3.1 -REFRESH AUTOMATIQUE INTELLIGENT SI MATCH EN DIRECT
try:
    matchs_en_direct = supabase.table("Matchs").select("id").eq("statut", "LIVE").execute().data
    if matchs_en_direct:
        st_autorefresh(interval=300000, key="live_rugby_refresh")
        verifier_et_importer_matchs()
except Exception:
    pass

# 3.2 Tentative de reconnexion via COOKIE
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

# =====================================================================
# 4 - ÉCRAN DE CONNEXION / INSCRIPTION
# =====================================================================
if st.session_state.user_id is None:
    st.title("🏉 Pronos Top 14")
    onglet_connexion = st.tabs(["Se connecter", "S'inscrire", "Mot de passe oublié"])
    
    with onglet_connexion[0]:
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

    with onglet_connexion[1]:
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

    with onglet_connexion[2]:
        st.subheader("Réinitialiser mon mot de passe")
        reset_email = st.text_input("Entrez votre adresse email de connexion", key="reset_mail")
        if st.button("Envoyer le lien de récupération"):
            if reset_email:
                try:
                    supabase.auth.reset_password_for_email(reset_email)
                    st.success("✉️ Si ce compte existe, un email de réinitialisation vous a été envoyé !")
                except Exception as e: st.error(f"Erreur : {e}")
            else: st.warning("Veuillez renseigner votre adresse email.")

# =====================================================================
# 5 - INTERFACE PRINCIPALE (UTILISATEUR CONNECTÉ)
# =====================================================================
else:
    # --- 5.1 - CONFIGURATION DES ONGLETS ACCESSIBLES ---
    icones_navigation = ["📊", "🏉", "📅"]
    if st.session_state.is_admin:
        icones_navigation.append("⚙️")

    # --- 5.2 - INJECTION DU STYLE CSS PARFAITEMENT CIBLÉ ---
# 5.2 (Ajout au CSS existant) - DESIGN DES CARTES PRONOS
    st.markdown("""
    <style>
        .match-card {
            background-color: #ffffff;
            padding: 20px;
            border-radius: 15px;
            border: 1px solid #e2e8f0;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .match-title {
            font-weight: 800;
            font-size: 1.2em;
            color: #1e3a8a;
            margin-bottom: 15px;
            text-align: center;
        }
        .btn-bulle {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            background: #f1f5f9;
            margin: 2px;
        }
    </style>
    """, unsafe_allow_html=True)

    # --- 5.3 - EN-TÊTE DU COMPOSANT RADIO DE NAVIGATION ---
    try:
        index_defaut = icones_navigation.index(st.session_state.onglet_actif)
    except ValueError:
        index_defaut = 0

    # 5.4 - L'ancre HTML qui sert de point d'attache au CSS exclusif
    st.markdown('<div class="barre-navigation-fixe"></div>', unsafe_allow_html=True)
    
    choix_onglet = st.radio(
        "MenuPrincipal",
        options=icones_navigation,
        index=index_defaut,
        horizontal=True,
        label_visibility="collapsed",
        key="MenuPrincipal" 
    )

    # 5.5 - Intercepteur de clic ultra-rapide
    if choix_onglet != st.session_state.onglet_actif:
        st.session_state.onglet_actif = choix_onglet
        st.rerun()

    # --- 5.6 - EN-TÊTE DE LA PAGE AVEC DÉCONNEXION ---
    col_vide, col_deco = st.columns([4, 1])
    with col_deco:
        if st.button("🚪 Déconnexion", key="btn_logout", use_container_width=True):
            st.session_state.user_id = None
            st.session_state.is_admin = False
            st.session_state.pseudo = ""
            st.rerun()
            
    st.markdown("---")

    # --- 5.7 - CHARGEMENT DU BARÈME ET DE LA CONFIGURATION ---
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
    # 6 -CONTENU DE L'ONGLET 1 : CLASSEMENT GÉNÉRAL
    # =====================================================================
    if st.session_state.onglet_actif == "📊":
        st.markdown(f"### 🏉 Bienvenue sur ton tableau de bord, **{st.session_state.pseudo}** !")
        
        try:
            joueur_connecte = supabase.table("Joueurs").select("*").eq("id", st.session_state.user_id).single().execute().data
            tous_les_joueurs = supabase.table("Joueurs").select("*").order("score", desc=True).execute().data
            
            rang_joueur = "-"
            if tous_les_joueurs:
                for idx, j in enumerate(tous_les_joueurs):
                    if j['id'] == st.session_state.user_id:
                        rang_joueur = idx + 1
                        break
            
            pronos_joueur = supabase.table("Pronostics").select("*, Matchs(*)").eq("user_id", st.session_state.user_id).execute().data
            stats_bons_gagnants, stats_parfaits, stats_oses = 0, 0, 0
            
            for p in pronos_joueur:
                match = p.get('Matchs')
                if match and match.get('score_dom') is not None and match.get('score_ext') is not None:
                    sc_dom, sc_ext = match['score_dom'], match['score_ext']
                    vrai_gagnant = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                    vrai_ecart_points = abs(sc_dom - sc_ext)
                    
                    vraie_tranche = "1-6"
                    if 7 <= vrai_ecart_points <= 10: vraie_tranche = "7-10"
                    elif 11 <= vrai_ecart_points <= 15: vraie_tranche = "11-15"
                    elif 16 <= vrai_ecart_points <= 20: vraie_tranche = "16-20"
                    elif 21 <= vrai_ecart_points <= 30: vraie_tranche = "21-30"
                    elif 31 <= vrai_ecart_points <= 40: vraie_tranche = "31-40"
                    elif 41 <= vrai_ecart_points <= 50: vraie_tranche = "41-50"
                    elif vrai_ecart_points >= 51: vraie_tranche = "51+"
                    
                    if p['gagnant_prevu'] == vrai_gagnant:
                        stats_bons_gagnants += 1
                        if p['ecart_prevu'] == vraie_tranche:
                            stats_parfaits += 1
                        
                        tous_pronos_match = supabase.table("Pronostics").select("gagnant_prevu").eq("match_id", match['id']).execute().data
                        if tous_pronos_match:
                            total_m = len(tous_pronos_match)
                            nb_bons_m = sum(1 for pm in tous_pronos_match if pm['gagnant_prevu'] == vrai_gagnant)
                            pct_m = (nb_bons_m / total_m) * 100 if total_m > 0 else 0
                            if pct_m <= seuil_ose_cfg:
                                stats_oses += 1
                                
        except Exception:
            joueur_connecte = {"score": 0}
            tous_les_joueurs = []
            rang_joueur = "-"
            stats_bons_gagnants, stats_parfaits, stats_oses = 0, 0, 0

        suffixe = "er" if rang_joueur == 1 else "e"
        
        st.markdown(f"""
        <div style="background-color: #f0f4f8; border-radius: 16px; padding: 15px; border: 1px solid #d3e2f2; margin-bottom: 25px;">
            <div style="display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 90px; max-width: 110px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #627d98; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🏆 Rang</span>
                    <span style="color:#1e3a8a; font-size: 26px; font-weight: 900;">{rang_joueur}{suffixe}</span>
                    <span style="display:block; font-size:10px; color:#627d98;">/{len(tous_les_joueurs)}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 90px; max-width: 110px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #627d98; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🎯 Score</span>
                    <span style="color:#1e3a8a; font-size: 26px; font-weight: 900;">{joueur_connecte.get('score', 0) if joueur_connecte else 0}</span>
                    <span style="display:block; font-size:10px; color:#627d98;">pts</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #43a047; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">✅ Vainqueurs</span>
                    <span style="color: #43a047; font-size: 32px; font-weight: 900;">{stats_bons_gagnants}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #0a3613; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">⭐ + Écart</span>
                    <span style="color: #0a3613; font-size: 32px; font-weight: 900;">{stats_parfaits}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #b7791f; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🔥 Osés</span>
                    <span style="color: #b7791f; font-size: 32px; font-weight: 900;">{stats_oses}</span>
                </div>
            </div>
        </div>
        """.replace("\n", ""), unsafe_allow_html=True)

        st.subheader("📊 Classement Général de la Communauté")
        if tous_les_joueurs:
            lignes_html = ""
            for index, joueur in enumerate(tous_les_joueurs):
                rang = index + 1
                prefixe_rang = "🥇 1er" if rang == 1 else ("🥈 2e" if rang == 2 else ("🥉 3e" if rang == 3 else f"{rang}e"))
                
                if joueur['id'] == st.session_state.user_id:
                    style_ligne = "background-color: #cbd5e1; font-weight: bold; border-left: 5px solid #1e3a8a; color: #000000;"
                    pseudo_affiche = f"{joueur['pseudo']} (Toi)"
                else:
                    style_ligne = "color: #2d3748;"
                    pseudo_affiche = joueur['pseudo']
                
                lignes_html += f'<tr style="{style_ligne} border-bottom: 1px solid #e2e8f0;"><td style="padding: 12px; text-align: left; color: inherit;">{prefixe_rang}</td><td style="padding: 12px; text-align: left; color: inherit;">{pseudo_affiche}</td><td style="padding: 12px; text-align: right; font-weight: bold; color: #000000;">{joueur["score"]} pts</td></tr>'
            
            st.markdown(f"""
            <div style="background-color: #f8fafc; border-radius: 12px; padding: 15px; border: 1px solid #e2e8f0;">
                <table style="width: 100%; border-collapse: collapse; font-family: sans-serif; color: #2d3748;">
                    <thead>
                        <tr style="border-bottom: 2px solid #cbd5e1; color: #64748b; font-size: 14px;">
                            <th style="padding: 10px; text-align: left; color: #64748b;">Position</th>
                            <th style="padding: 10px; text-align: left; color: #64748b;">Joueur</th>
                            <th style="padding: 10px; text-align: right; color: #64748b;">Score</th>
                        </tr>
                    </thead>
                    <tbody>{lignes_html}</tbody>
                </table>
            </div>
            """.replace("\n", ""), unsafe_allow_html=True)
        else:
            st.info("Le classement est vide pour le moment.")

    # =====================================================================
    # 7 - CONTENU DE L'ONGLET 2 : FAIRE MES PRONOSTICS
    # =====================================================================
    elif st.session_state.onglet_actif == "🏉":
        st.title("✍ *Saisir les Pronostics*")

        with st.expander("ℹ️ Rappel des règles et du barème des points"):
            st.markdown(f"""
            * **Bon Vainqueur / Match Nul** : `{pts_gagnant_cfg} points`
            * **Tranche d'écart exacte** : `+{pts_ecart_cfg} points` (soit `{pts_parfait_cfg} points` pour un prono parfait)
            * **🔥 Mode OSÉ Actif** : Si moins de `{seuil_ose_cfg}%` des joueurs trouvent le score parfait (Vainqueur + Écart), leurs points sur ce match sont multipliés par `{mult_ose_cfg}` (soit `{pts_parfait_cfg * mult_ose_cfg} points` au lieu de `{pts_parfait_cfg}`) !
            """)

        id_joueur_cible = st.session_state.user_id
        if st.session_state.is_admin:
            try:
                liste_membres = supabase.table("Joueurs").select("id, pseudo").order("pseudo").execute().data
                if liste_membres:
                    index_admin = 0
                    for idx, m in enumerate(liste_membres):
                        if m['id'] == st.session_state.user_id: index_admin = idx; break
                    st.warning("🛠 **Mode Admin actif** : Vous pouvez pronostiquer à la place d'un autre joueur.")
                    choix_membre = st.selectbox("Sélectionner le compte joueur à utiliser :", options=liste_membres, format_func=lambda x: x['pseudo'], index=index_admin)
                    if choix_membre: id_joueur_cible = choix_membre['id']
            except Exception as e: st.error(f"Erreur membres : {e}")

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
                    index_defaut = options_rep.index(deja_repondu[0]['reponse_joueur']) if deja_repondu and deja_repondu[0]['reponse_joueur'] in options_rep else 0
                    st.radio("Ta réponse :", options=options_rep, index=index_defaut, key=f"bonus_q_{q['id']}", on_change=sauvegarder_bonus_auto, args=(q['id'], id_joueur_cible))
                    if deja_repondu: st.caption("✅ _Enregistré automatiquement_")
                    st.markdown("---")
            else: st.write("Aucune question bonus ouverte actuellement.")
        except Exception as e: st.error(f"Erreur questions bonus : {e}")
            
            # 7.1 - MATCHS OUVERTS (VERSION UI AMÉLIORÉE)
            st.subheader("🏉 Matchs à venir")
            if matchs_ouverts:
                for m in matchs_ouverts:
                    # Conteneur de carte
                    with st.container():
                        st.markdown(f'<div class="match-card">', unsafe_allow_html=True)
                        st.markdown(f'<div class="match-title">{m["equipe_dom"]} vs {m["equipe_ext"]}</div>', unsafe_allow_html=True)
                        
                        prono_existant = supabase.table("Pronostics").select("*").eq("user_id", id_joueur_cible).eq("match_id", m['id']).execute().data
                        
                        # Grille pour les choix
                        col1, col2 = st.columns(2)
                        with col1:
                            # Ton système de radio existant, mais plus propre
                            st.radio("Vainqueur", ["...", m['equipe_dom'], m['equipe_ext'], "Match Nul"], 
                                     key=f"w_{m['id']}", on_change=sauvegarder_prono_auto, args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible))
                        with col2:
                            st.selectbox("Écart (pts)", ["..."] + TRANCHES_ECARTS, 
                                         key=f"m_{m['id']}", on_change=sauvegarder_prono_auto, args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible))
                        
                        if prono_existant:
                            st.success("✅ Pronostic enregistré")
                        st.markdown('</div>', unsafe_allow_html=True)
            else: 
                st.info("Aucun match ouvert.")
        except Exception as e: st.error(f"Erreur match : {e}")

    # =====================================================================
    # 8 - CONTENU DE L'ONGLET 3 : RÉSULTATS & DIRECT
    # =====================================================================
    elif st.session_state.onglet_actif == "📅":
        st.title("📊 Résultats & Direct")
        if matchs_en_direct:
            st.success("⚡ **Mode Direct Actif** : Les scores se rafraîchissent automatiquement toutes les 5 minutes.")
            
# 8.1 - RÉSULTATS & DIRECT (VERSION UI + RÈGLES CONSERVÉES)
st.subheader("🏉 Matchs Clos / En cours")
try:
    matchs = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
    
    for m in matchs:
        # Calcul des conditions pour le match
        sc_dom, sc_ext = m.get('score_dom', 0), m.get('score_ext', 0)
        vrai_gagnant_brut = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
        vrai_ecart = abs(sc_dom - sc_ext)
        
        # Déterminer la tranche (ta logique actuelle)
        vraie_tranche = "1-6" # ... (ajoute ici tes conditions if/elif pour la tranche)
        
        # UI : Utilisation d'un expander stylisé
        label_live = "🔴 EN DIRECT" if m['statut'] == 'LIVE' else ""
        with st.expander(f"{m['equipe_dom']} {sc_dom} - {sc_ext} {m['equipe_ext']} {label_live}"):
            
            # --- LOGIQUE DES POINTS CONSERVÉE ---
            all_pronos = supabase.table("Pronostics").select("gagnant_prevu, ecart_prevu, Joueurs(pseudo)").eq("match_id", m['id']).execute().data
            
            if all_pronos:
                # Calcul pour le mode OSÉ
                total_p = len(all_pronos)
                nb_bons = sum(1 for p in all_pronos if p['gagnant_prevu'] == vrai_gagnant_brut)
                pct_m = (nb_bons / total_p) * 100 if total_p > 0 else 0
                est_ose = pct_m <= seuil_ose_cfg and nb_bons > 0
                
                for p in all_pronos:
                    # Ici tu réintègres tes if/else de calcul de points
                    pts_gagnes = 0
                    if p['gagnant_prevu'] == vrai_gagnant_brut:
                        pts_base = pts_gagnant_cfg + (pts_ecart_cfg if p['ecart_prevu'] == vraie_tranche else 0)
                        pts_gagnes = pts_base * mult_ose_cfg if est_ose else pts_base
                    
                    # Affichage personnalisé
                    badge = "🔥 OSÉ" if est_ose else ("⭐ PARFAIT" if pts_gagnes >= (pts_gagnant_cfg + pts_ecart_cfg) else "✅")
                    st.markdown(f"👤 **{p['Joueurs']['pseudo']}** : `{badge} +{pts_gagnes} pts`")
            else:
                st.write("Aucun prono.")
except Exception as e:
    st.error(f"Erreur : {e}")
    # =====================================================================
    # 9 - CONTENU DE L'ONGLET 4 : CONSOLE ADMINISTRATION PRIVÉE
    # =====================================================================
    elif st.session_state.onglet_actif == "⚙️" and st.session_state.is_admin:
        st.title("⚙️ Console d'Administration Privée")
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🎯 Configuration", "➕ Matchs Manuels", "🎁 Questions Bonus", "🔄 Synchro Scraping", "🚨 Zone Danger"])
      # 9.1 - TAB 1   
        with tab1:
            st.subheader("🎛️ Configuration du Barème")
            try: current_config = supabase.table("Configuration").select("*").eq("id", "default_config").single().execute().data
            except Exception: current_config = {}
            
            with st.form("form_points"):
                val_gagnant = st.number_input("Points pour le bon vainqueur", value=current_config.get("pts_gagnant", 3) if current_config else 3)
                val_ecart = st.number_input("Points pour le bon écart", value=current_config.get("pts_ecart", 2) if current_config else 2)
                val_seuil = st.number_input("Seuil de déclenchement du mode Osé (en %)", value=current_config.get("seuil_poursentage_ose", 20) if current_config else 20)
                val_mult = st.number_input("Multiplicateur Osé (ex: 2)", value=current_config.get("multiplicateur_ose", 2) if current_config else 2)
                if st.form_submit_button("💾 Sauvegarder"):
                    supabase.table("Configuration").upsert({"id": "default_config", "pts_gagnant": val_gagnant, "pts_ecart": val_ecart, "seuil_poursentage_ose": val_seuil, "multiplicateur_ose": val_mult}).execute()
                    st.success("Barème enregistré !")
                    st.rerun()
#9.2 - TAB 2
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
                        supabase.table("Matchs").insert({"id": id_m, "equipe_dom": eq_dom, "equipe_ext": eq_ext, "date_match": dt_combine, "score_dom": None, "score_ext": None, "statut": "NS"}).execute()
                        st.success("Match créé de force !")
                        st.rerun()
            
            st.markdown("---")
            st.subheader("📝 Saisir le résultat d'un match & Distribuer les points")
            try:
                tous_matchs = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
                if tous_matchs:
                    match_selectionne = st.selectbox("Sélectionner le match :", options=tous_matchs, format_func=lambda m: f"{m['equipe_dom']} ({m['score_dom'] if m['score_dom'] is not None else '?'}) vs ({m['score_ext'] if m['score_ext'] is not None else '?'}) {m['equipe_ext']} - [{m['statut']}]")
                    if match_selectionne:
                        with st.form(f"form_score_manual_{match_selectionne['id']}"):
                            nouveau_score_dom = st.number_input(f"Score {match_selectionne['equipe_dom']}", min_value=0, value=match_selectionne['score_dom'] if match_selectionne['score_dom'] is not None else 0)
                            nouveau_score_ext = st.number_input(f"Score {match_selectionne['equipe_ext']}", min_value=0, value=match_selectionne['score_ext'] if match_selectionne['score_ext'] is not None else 0)
                            liste_statuts = ["NS", "FT", "LIVE"]
                            statut_index = liste_statuts.index(match_selectionne['statut']) if match_selectionne['statut'] in liste_statuts else 1
                            nouveau_statut = st.selectbox("Statut du match", options=liste_statuts, index=statut_index)
                            if st.form_submit_button("💾 1. Enregistrer le résultat"):
                                supabase.table("Matchs").update({"score_dom": nouveau_score_dom, "score_ext": nouveau_score_ext, "statut": nouveau_statut}).eq("id", match_selectionne['id']).execute()
                                r_res = st.success("Résultat enregistré !")
                                st.rerun()

                        if match_selectionne['statut'] == "FT":
                            if st.button(f"🎯 Calculer et Distribuer les points", type="primary"):
                                with st.spinner("Calcul..."):
                                    sc_dom, sc_ext = match_selectionne['score_dom'], match_selectionne['score_ext']
                                    if sc_dom is not None and sc_ext is not None:
                                        vrai_gagnant_brut = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                                        vrai_ecart_points = abs(sc_dom - sc_ext)
                                        vraie_tranche = "1-6"
                                        if 7 <= vrai_ecart_points <= 10: vraie_tranche = "7-10"
                                        elif 11 <= vrai_ecart_points <= 15: vraie_tranche = "11-15"
                                        elif 16 <= vrai_ecart_points <= 20: vraie_tranche = "16-20"
                                        elif 21 <= vrai_ecart_points <= 30: vraie_tranche = "21-30"
                                        elif 31 <= vrai_ecart_points <= 40: vraie_tranche = "31-40"
                                        elif 41 <= vrai_ecart_points <= 50: vraie_tranche = "41-50"
                                        elif vrai_ecart_points >= 51: vraie_tranche = "51+"
                                        
                                        pronos = supabase.table("Pronostics").select("user_id, gagnant_prevu, ecart_prevu").eq("match_id", match_selectionne['id']).execute().data
                                        compteur_updates = 0
                                        if pronos:
                                            total_pronos = len(pronos)
                                            nb_bons_vainqueurs = sum(1 for p in pronos if p['gagnant_prevu'] == vrai_gagnant_brut)
                                            pourcentage_vainqueur = (nb_bons_vainqueurs / total_pronos) * 100 if total_pronos > 0 else 0
                                            est_ose = pourcentage_vainqueur <= seuil_ose_cfg and nb_bons_vainqueurs > 0
                                            
                                            for p in pronos:
                                                pts_gagnes = 0
                                                if p['gagnant_prevu'] == vrai_gagnant_brut:
                                                    pts_base_match = pts_gagnant_cfg
                                                    if p['ecart_prevu'] == vraie_tranche: pts_base_match += pts_ecart_cfg
                                                    pts_gagnes = pts_base_match * mult_ose_cfg if est_ose else pts_base_match
                                                
                                                if pts_gagnes > 0:
                                                    joueur_id = p['user_id']
                                                    j_data = supabase.table("Joueurs").select("score").eq("id", joueur_id).single().execute().data
                                                    if j_data:
                                                        nouveau_global = j_data.get('score', 0) + pts_gagnes
                                                        supabase.table("Joueurs").update({"score": nouveau_global}).eq("id", joueur_id).execute()
                                                        compteur_updates += 1
                                        st.success(f"🎉 Points distribués ! {compteur_updates} joueurs mis à jour.")
                                        st.balloons()
                                        time.sleep(1)
                                        st.rerun()
            except Exception as e: st.error(f"Erreur admin matchs : {e}")
#9.3 - TAB 3
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
                        supabase.table("Questions_Bonus").insert({"question": intitule, "choix_reponse": choix, "date_limite": dt_lim_combine, "statut": "En cours", "points": pts_bonus}).execute()
                        st.success("Question bonus en ligne !")
                        st.rerun()
            
            st.markdown("---")
            st.subheader("✅ Corriger et Valider une question bonus")
            try:
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
            except Exception as e: st.error(f"Erreur validation bonus : {e}")
#9.4 - TAB 4
        with tab4:
            st.subheader("🔄 Lanceur de Scraping Manuel")
            if st.button("⚡ Lancer la Synchronisation"):
                with st.spinner("Scraping en cours..."):
                    nb = verifier_et_importer_matchs()
                    st.success(f"Terminé ! {nb} matchs traités avec succès.")
                    st.rerun()
#9.5 - TAB 5 
        with tab5:
            st.subheader("🚨 Zone de Danger")
            confirmation_secu = st.checkbox("Je confirme vouloir tout réinitialiser.", key="danger_zone_confirm")
            if st.button("🔥 Réinitialiser l'application", type="primary", disabled=not confirmation_secu):
                with st.spinner("Nettoyage..."):
                    try:
                        supabase.table("Pronostics").delete().not_.is_("id", "null").execute()
                        supabase.table("Réponses_Questions").delete().not_.is_("id", "null").execute()
                        supabase.table("Matchs").delete().not_.is_("id", "null").execute()
                        supabase.table("Questions_Bonus").delete().not_.is_("id", "null").execute()
                        supabase.table("Joueurs").update({"score": 0}).not_.is_("id", "null").execute()
                        st.success("🎉 Reset saison terminé !")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                    except Exception as e: st.error(f"Erreur reset : {e}")
