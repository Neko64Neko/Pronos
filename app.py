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
    """Sauvegarde automatique de la réponse à une question bonus."""
    # Correction : On utilise les bons noms de variables passés en arguments (question_id et user_id_cible)
    cle_state = f"q_{question_id}_{user_id_cible}"
    if cle_state in st.session_state:
        valeur = st.session_state[cle_state]
        try:
            # Vérification si une réponse existe déjà
            rep_existante = supabase.table("Réponses_Questions").select("*").eq("user_id", user_id_cible).eq("question_id", question_id).execute().data
            
            if rep_existante:
                # Mise à jour avec la colonne reponse_joueur
                supabase.table("Réponses_Questions").update({
                    "reponse_joueur": valeur
                }).eq("id", rep_existante[0]['id']).execute()
            else:
                # Insertion avec la colonne reponse_joueur
                supabase.table("Réponses_Questions").insert({
                    "user_id": user_id_cible,
                    "question_id": question_id,
                    "reponse_joueur": valeur
                }).execute()
        except Exception as e:
            st.error(f"Erreur lors de la sauvegarde de la question : {e}")
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

    # --- 5.3 - CONFIGURATION DES ONGLETS DE NAVIGATION ---
    if "mode_admin_actif" not in st.session_state:
        st.session_state.mode_admin_actif = True  # Activé par défaut
    
    if st.session_state.is_admin:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🛠️ Options Développeur")
        st.session_state.mode_admin_actif = st.sidebar.toggle(
            "Activer les droits d'édition", 
            value=st.session_state.mode_admin_actif,
            help="Désactivez cette option pour naviguer et tester l'application comme un joueur classique."
        )
    
    if st.session_state.is_admin:
        options_menu = ["📊", "🏉", "📅", "⚙️"]
        labels_menu = {
            "📊": "📊 Général",
            "🏉": "🏉 Pronos",
            "📅": "📅 Scores",
            "⚙️": "⚙️ Admin"
        }
    else:
        options_menu = ["📊", "🏉", "📅"]
        labels_menu = {
            "📊": "📊 Général",
            "🏉": "🏉 Pronos",
            "📅": "📅 Scores"
        }

    st.markdown("""
        <style>
            div[data-testid="stSegmentedControl"] {
                width: 100% !important;
                display: flex !important;
            }
            div[data-testid="stSegmentedControl"] button {
                flex: 1 !important;
                min-width: 0 !important;
                text-align: center !important;
                padding: 12px 4px !important;
                font-weight: bold !important;
                font-size: 12px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # 5.4 & 5.5 - RENDU ET LOGIQUE DE NAVIGATION
    choix_menu = st.segmented_control(
        "Navigation",
        options=options_menu,
        format_func=lambda x: labels_menu.get(x, x),
        default=st.session_state.onglet_actif,
        label_visibility="collapsed",
        key="barre_navigation_segmentee"
    )

    if choix_menu and choix_menu != st.session_state.onglet_actif:
        st.session_state.onglet_actif = choix_menu
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
    # 6 - CONTENU DE L'ONGLET 1 : CLASSEMENT GÉNÉRAL
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
# 7 - CONTENU DE L'ONGLET 2 : PRONOSTICS
# =====================================================================
if st.session_state.onglet_actif == "🏉":
    st.title("🏉 Espace Pronostics")
    
    # Initialisation de la sécurité mode admin si elle n'existe pas
    if "mode_admin_pronos" not in st.session_state:
        st.session_state.mode_admin_pronos = False

    # --- 7.1 - GESTION DES DROITS ET DU TOGGLE (RÉSERVÉ ADMIN) ---
    liste_joueurs = supabase.table("Joueurs").select("*").order("pseudo").execute().data
    
    if liste_joueurs:
        noms_joueurs = [j['pseudo'] for j in liste_joueurs]
        utilisateur_actuel = st.session_state.get("pseudo", "")
        
        # Détermination du pseudo cible par défaut
        nom_selectionne = utilisateur_actuel
        
        # Si l'utilisateur est admin, on lui affiche le bouton ON/OFF en haut de la page
        if st.session_state.is_admin:
            st.session_state.mode_admin_pronos = st.toggle(
                "🧙‍♂️ Activer le Mode Admin (permet de pronostiquer pour un autre joueur)", 
                value=st.session_state.mode_admin_pronos
            )
            
            # Si le mode admin est activé, on affiche la liste déroulante pour écraser "nom_selectionne"
            if st.session_state.mode_admin_pronos:
                index_par_defaut = noms_joueurs.index(utilisateur_actuel) if utilisateur_actuel in noms_joueurs else 0
                nom_selectionne = st.selectbox(
                    "🎯 Choisir le joueur pour qui vous allez pronostiquer :", 
                    options=noms_joueurs, 
                    index=index_par_defaut
                )
            else:
                st.info(f"👤 Mode Personnel : Vous pronostiquez pour votre compte : **{nom_selectionne}**")
        else:
            st.info(f"👤 Connecté en tant que : **{nom_selectionne}**")
            
        # Récupération sécurisée du dictionnaire du joueur cible
        joueur_cible = next((j for j in liste_joueurs if j['pseudo'] == nom_selectionne), None)
        
        if joueur_cible:
            id_joueur_cible = joueur_cible['id']
            
# --- 7.2 - ZONE DE JEU (QUESTIONS + MATCHS) ---
            with st.spinner("Chargement de la grille..."):
                try:
                    # 7.2.1 - SECTION QUESTIONS BONUS
                    st.subheader("🎯 Questions Bonus")
                    questions = supabase.table("Questions_Bonus").select("*").execute().data
                    
                    if questions:
                        for q in questions:
                            rep_existante = supabase.table("Réponses_Questions").select("*").eq("user_id", id_joueur_cible).eq("question_id", q['id']).execute().data
                            
                            valeur_defaut = rep_existante[0]['reponse_joueur'] if rep_existante and rep_existante[0].get('reponse_joueur') is not None else ""
                            texte_question = q.get('question') or "Question Bonus"
                            pts_bonus = q.get('points_bonus') or q.get('points') or 0
                            
                            st.text_input(
                                f"❓ {texte_question} ({pts_bonus} pts)",
                                value=valeur_defaut,
                                key=f"q_{q['id']}_{id_joueur_cible}",
                                on_change=sauvegarder_bonus_auto,
                                args=(q['id'], id_joueur_cible)
                            )
                    else:
                        st.caption("Aucune question bonus pour le moment.")
                except Exception as e:
                    st.error(f"Erreur lors du chargement des questions bonus : {e}")
                        
                # 7.2.2 - SECTION MATCHS OUVERTS
                st.markdown("""<hr style="border: 1px solid #e2e8f0; margin: 30px 0 20px 0;">""", unsafe_allow_html=True)
                st.subheader("🏉 Liste des Matchs")

                try:
                    matchs_potentiels = supabase.table("Matchs").select("*").neq("statut", "FT").execute().data
                    matchs_visibles = []
                    
                    if matchs_potentiels:
                        for m in matchs_potentiels:
                            try:
                                date_brute = m['date_match'].split("+")[0].split("Z")[0]
                                dt_match = datetime.fromisoformat(date_brute)
                                if maintenant_paris < dt_match or (st.session_state.is_admin and st.session_state.mode_admin_actif):
                                    matchs_visibles.append(m)
                            except Exception:
                                if m['statut'] == "NS" or (st.session_state.is_admin and st.session_state.mode_admin_actif):
                                    matchs_visibles.append(m)

                    if matchs_visibles:
                        matchs_visibles = sorted(matchs_visibles, key=lambda x: x['date_match'])
                        
                        for m in matchs_visibles:
                            with st.container():
                                st.markdown(f'<div class="match-card">', unsafe_allow_html=True)
                                st.markdown(f'<div class="match-title">{m["equipe_dom"]} vs {m["equipe_ext"]}</div>', unsafe_allow_html=True)
                                
                                bouton_bloque = False
                                try:
                                    date_brute = m['date_match'].split("+")[0].split("Z")[0]
                                    dt_obj = datetime.fromisoformat(date_brute)
                                    date_affiche = dt_obj.strftime("%d/%m/%Y à %H:%M")
                                    match_commence = maintenant_paris >= dt_obj
                                    
                                    if match_commence:
                                        if st.session_state.is_admin and st.session_state.mode_admin_actif:
                                            st.markdown(f"<div style='text-align: center; color: #b7791f; font-size: 0.9em; font-weight: bold; margin-bottom: 10px;'>⚠️ Match commencé ({date_affiche}) - Autorisé (Admin)</div>", unsafe_allow_html=True)
                                        else:
                                            st.markdown(f"<div style='text-align: center; color: #dc2626; font-size: 0.9em; font-weight: bold; margin-bottom: 10px;'>🔒 Match commencé le {date_affiche}</div>", unsafe_allow_html=True)
                                            bouton_bloque = True
                                    else:
                                        st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.9em; margin-bottom: 10px;'>📅 Match prévu le {date_affiche}</div>", unsafe_allow_html=True)
                                except Exception:
                                    pass

                                prono_existant = supabase.table("Pronostics").select("*").eq("user_id", id_joueur_cible).eq("match_id", m['id']).execute().data
                                choix_actuel = ""
                                if prono_existant:
                                    g_prevu = prono_existant[0]['gagnant_prevu']
                                    if g_prevu == "home": choix_actuel = m['equipe_dom']
                                    elif g_prevu == "away": choix_actuel = m['equipe_ext']
                                    elif g_prevu == "draw": choix_actuel = "Match Nul"

                                st.caption("Sélectionner le Vainqueur :")
                                
                                st.markdown("""
                                    <style>
                                        .zone-matchs [data-testid="stHorizontalBlock"] {
                                            flex-wrap: nowrap !important;
                                            gap: 4px !important;
                                            width: 100% !important;
                                            overflow: hidden !important;
                                            display: flex !important;
                                            flex-direction: row !important;
                                        }
                                        .zone-matchs [data-testid="stHorizontalBlock"] > div {
                                            width: calc(33.33% - 4px) !important;
                                            min-width: 0 !important;
                                            flex: 1 1 0% !important;
                                        }
                                        .zone-matchs [data-testid="stHorizontalBlock"] button {
                                            width: 100% !important;
                                            max-width: 100% !important;
                                            min-width: 0 !important;
                                            padding: 4px 4px !important;
                                            overflow: hidden !important;
                                        }
                                        .zone-matchs [data-testid="stHorizontalBlock"] button p {
                                            overflow: hidden !important;
                                            text-overflow: ellipsis !important;
                                            white-space: nowrap !important;
                                            font-size: 11px !important;
                                        }
                                    </style>
                                """, unsafe_allow_html=True)
                                
                                st.markdown('<div class="zone-matchs">', unsafe_allow_html=True)
                                col_a, col_b, col_c = st.columns(3)
                                
                                with col_a:
                                    type_a = "primary" if choix_actuel == m['equipe_dom'] else "secondary"
                                    if st.button(f"🏉 {m['equipe_dom']}", key=f"btn_dom_{m['id']}_{id_joueur_cible}", type=type_a, use_container_width=True, disabled=bouton_bloque):
                                        st.session_state[f"w_{m['id']}"] = m['equipe_dom']
                                        sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                        st.rerun()
                                        
                                with col_b:
                                    type_b = "primary" if choix_actuel == "Match Nul" else "secondary"
                                    if st.button("🤝 Nul", key=f"btn_nul_{m['id']}_{id_joueur_cible}", type=type_b, use_container_width=True, disabled=bouton_bloque):
                                        st.session_state[f"w_{m['id']}"] = "Match Nul"
                                        sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                        st.rerun()
                                        
                                with col_c:
                                    type_c = "primary" if choix_actuel == m['equipe_ext'] else "secondary"
                                    if st.button(f"🏉 {m['equipe_ext']}", key=f"btn_ext_{m['id']}_{id_joueur_cible}", type=type_c, use_container_width=True, disabled=bouton_bloque):
                                        st.session_state[f"w_{m['id']}"] = m['equipe_ext']
                                        sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                        st.rerun()

                                st.markdown('</div>', unsafe_allow_html=True)

                                st.markdown("<br>", unsafe_allow_html=True)
                                
                                # CORRECTION : On s'assure de recalculer l'index basé sur prono_existant qui utilise id_joueur_cible
                                index_ecart_defaut = 0
                                if prono_existant and prono_existant[0].get('ecart_prevu') in TRANCHES_ECARTS:
                                    index_ecart_defaut = TRANCHES_ECARTS.index(prono_existant[0]['ecart_prevu']) + 1
                                
                                # Le composant va maintenant correctement afficher l'écart du joueur choisi
                                st.selectbox(
                                    "Écart (pts)", 
                                    ["..."] + TRANCHES_ECARTS, 
                                    index=index_ecart_defaut,
                                    key=f"m_{m['id']}_{id_joueur_cible}", 
                                    on_change=sauvegarder_prono_auto, 
                                    args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible),
                                    disabled=bouton_bloque
                                )
                                
                                if prono_existant:
                                    st.success("✅ Pronostic enregistré")
                                st.markdown('</div>', unsafe_allow_html=True)
                    else: 
                        st.info("Aucun match disponible à pronostiquer.")
                except Exception as e: 
                    st.error(f"Erreur lors du chargement de la grille : {e}")
        else:
            st.error("Impossible de récupérer les informations du joueur sélectionné.")
    else:
        st.warning("⚠️ Aucun joueur trouvé dans la base.")

# =====================================================================
# 8 - CONTENU DE L'ONGLET 3 : RÉSULTATS & DIRECT (COULEURS ADAPTÉES)
# =====================================================================
elif st.session_state.onglet_actif == "📅":
    st.title("📅 Résultats & Matchs en Direct")
    
    # Récupération des valeurs du barème configurées par l'admin (ou valeurs par défaut)
    coef_vainqueur = st.session_state.get("pts_vainqueur", 2)
    coef_ecart = st.session_state.get("pts_ecart", 2)
    pct_max_ose = st.session_state.get("pct_ose", 20)
    multiplicateur_ose = st.session_state.get("mult_ose", 2.0)
    
    with st.spinner("Mise à jour des scores..."):
        st.subheader("🏉 Matchs Clos / En cours")
        try:
            tous_matchs_bdd = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
            matchs = []
            
            if tous_matchs_bdd:
                for m in tous_matchs_bdd:
                    try:
                        date_brute = m['date_match'].split("+")[0].split("Z")[0]
                        dt_match = datetime.fromisoformat(date_brute)
                        if m['statut'] in ["FT", "LIVE"] or maintenant_paris >= dt_match:
                            matchs.append(m)
                    except Exception:
                        if m['statut'] in ["FT", "LIVE"]:
                            matchs.append(m)
            
            if matchs:
                for m in matchs:
                    label_statut = ""
                    if m['statut'] == 'LIVE':
                        label_statut = " 🔴 EN DIRECT"
                    elif m['statut'] == 'NS':
                        label_statut = " ⏳ EN COURS (En attente du score)"
                    
                    sc_dom = m.get('score_dom') if m.get('score_dom') is not None else 0
                    sc_ext = m.get('score_ext') if m.get('score_ext') is not None else 0
                    
                    vrai_gagnant_brut = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                    diff = abs(sc_dom - sc_ext)
                    
                    if diff <= 6: vraie_tranche = "1-6"
                    elif diff <= 10: vraie_tranche = "7-10"
                    elif diff <= 15: vraie_tranche = "11-15"
                    elif diff <= 20: vraie_tranche = "16-20"
                    elif diff <= 30: vraie_tranche = "21-30"
                    elif diff <= 40: vraie_tranche = "31-40"
                    elif diff <= 50: vraie_tranche = "41-50"
                    else: vraie_tranche = "51+"

                    with st.expander(f"🏉 {m['equipe_dom']} {sc_dom} - {sc_ext} {m['equipe_ext']}{label_statut}"):
                        pronos = supabase.table("Pronostics").select("*, Joueurs(pseudo)").eq("match_id", m['id']).execute().data
                        
                        if pronos:
                            total_pronos_match = len(pronos)
                            mises_home = sum(1 for p in pronos if p['gagnant_prevu'] == "home")
                            mises_away = sum(1 for p in pronos if p['gagnant_prevu'] == "away")
                            
                            pct_home = (mises_home / total_pronos_match * 100) if total_pronos_match > 0 else 100
                            pct_away = (mises_away / total_pronos_match * 100) if total_pronos_match > 0 else 100
                            
                            st.markdown("**Pronostics des joueurs :**")
                            for p in pronos:
                                nom_joueur = p.get('Joueurs', {}).get('pseudo', 'Inconnu')
                                g_prevu = p['gagnant_prevu']
                                ec_prevu = p['ecart_prevu']
                                
                                nom_gagnant_prevu = m['equipe_dom'] if g_prevu == "home" else (m['equipe_ext'] if g_prevu == "away" else "Match Nul")
                                
                                pts = 0
                                badge_ose = ""
                                en_attente = False
                                
                                # Détermination de la couleur par défaut (rouge si perdant)
                                color = "#dc2626" 
                                
                                if m['statut'] == 'NS' and sc_dom == 0 and sc_ext == 0:
                                    en_attente = True
                                else:
                                    if g_prevu == vrai_gagnant_brut:
                                        base_match = coef_vainqueur
                                        is_ecart_exact = (ec_prevu == vraie_tranche and g_prevu != "draw")
                                        
                                        # Gestion de la couleur de base (Bleu si vainqueur simple, Vert si score/écart exact)
                                        if is_ecart_exact:
                                            base_match += coef_ecart
                                            color = "#10b981" # Vert
                                        else:
                                            color = "#2563eb" # Bleu
                                        
                                        # Vérification si c'est un prono osé
                                        is_ose = (g_prevu == "home" and pct_home <= pct_max_ose) or (g_prevu == "away" and pct_away <= pct_max_ose)
                                        
                                        if is_ose:
                                            pts = float(base_match * multiplicateur_ose)
                                            badge_ose = f" 🔥 **[OSÉ x{multiplicateur_ose}]**"
                                            color = "#d97706" # Doré / Ambre pour tout prono osé réussi
                                        else:
                                            pts = float(base_match)
                                
                                # Formatage final de l'affichage textuel
                                if en_attente:
                                    color = "orange"
                                    texte_points = "⏳ En attente"
                                else:
                                    pts_affiche = int(pts) if pts.is_integer() else pts
                                    accord_pts = "pt" if pts_affiche <= 1 else "pts"
                                    texte_points = f"{pts_affiche} {accord_pts}"
                                
                                st.markdown(f"- **{nom_joueur}** : {nom_gagnant_prevu} ({ec_prevu}){badge_ose} ➔ <span style='color:{color}; font-weight:bold;'>{texte_points}</span>", unsafe_allow_html=True)
                        else:
                            st.caption("Aucun pronostic enregistré pour ce match.")
            else:
                st.info("Aucun match terminé ou en cours pour le moment.")
        except Exception as e:
            st.error(f"Erreur lors du chargement des scores : {e}")
# =====================================================================
# 9 - CONTENU DE L'ONGLET 4 : ADMIN (SÉCURISÉ AVEC LE TOGGLE)
# =====================================================================
elif st.session_state.onglet_actif == "⚙️" and st.session_state.is_admin:
    
    # Si le bouton est sur OFF, on bloque l'accès visuel
    if not st.session_state.mode_admin_actif:
        st.title("⚙️ Panneau d'Administration")
        st.warning("⚠️ Le mode d'édition admin est actuellement désactivé. Activez-le dans la barre latérale pour modifier le barème, ajouter des matchs ou modifier des scores.")
    else:
        st.title("⚙️ Panneau d'Administration")
        
        # Ajout de l'onglet Barème & Points en premier
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "⚙️ Barème & Points",
            "➕ Ajouter Match", 
            "📝 Matchs Existants", 
            "🎯 Questions Bonus", 
            "🔄 Scraping", 
            "🚨 Danger"
        ])
    
    # 9.1 - TAB 1 : GESTION DES POINTS ET DU BARÈME
    with tab1:
        st.subheader("📊 Configuration du Barème de Points")
        st.info("Ajuste les coefficients ci-dessous. Ils seront appliqués lors du calcul des résultats.")
        
        # Initialisation des valeurs par défaut dans le session_state si elles n'existent pas
        if "pts_vainqueur" not in st.session_state: st.session_state.pts_vainqueur = 2
        if "pts_ecart" not in st.session_state: st.session_state.pts_ecart = 2
        if "pct_ose" not in st.session_state: st.session_state.pct_ose = 20
        if "mult_ose" not in st.session_state: st.session_state.mult_ose = 2.0
        
        with st.form("form_bareme_points"):
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                pts_v = st.number_input("Points Vainqueur trouvé", min_value=0, value=int(st.session_state.pts_vainqueur), step=1)
                pts_e = st.number_input("Points Écart parfait (Bonus)", min_value=0, value=int(st.session_state.pts_ecart), step=1)
            with col_b2:
                pct_o = st.number_input("% max de déclenchement prono osé", min_value=1, max_value=100, value=int(st.session_state.pct_ose), step=1, help="Si moins de X% des joueurs ont misé sur cette équipe, le prono devient 'osé'")
                mult_o = st.number_input("Multiplicateur du prono osé", min_value=1.0, max_value=10.0, value=float(st.session_state.mult_ose), step=0.5)
            
            if st.form_submit_button("💾 Sauvegarder le barème"):
                st.session_state.pts_vainqueur = pts_v
                st.session_state.pts_ecart = pts_e
                st.session_state.pct_ose = pct_o
                st.session_state.mult_ose = mult_o
                st.success("🎉 Barème mis à jour avec succès pour cette session !")
                time.sleep(1)
                st.rerun()

# 9.2 - TAB 2 : AJOUTER UN MATCH MANUELLEMENT
    with tab2:
        st.subheader("➕ Ajouter un Match Manuellement")
        with st.form("form_ajout_match", clear_on_submit=True):
            eq_dom = st.text_input("Équipe Domicile :")
            eq_ext = st.text_input("Équipe Extérieur :")
            date_m = st.date_input("Date du match :", value=datetime.now().date())
            heure_m = st.time_input("Heure du match :", value=datetime.now().time())
            
            submit_match = st.form_submit_button("Créer le Match")
            
            if submit_match:
                if eq_dom and eq_ext:
                    try:
                        # Fusion de la date et de l'heure
                        dt_combinee = datetime.combine(date_m, heure_m)
                        iso_date = dt_combinee.isoformat() + "Z"
                        
                        # CORRECTION : Génération d'un ID numérique unique aléatoire pour éviter le NOT NULL constraint
                        id_unique_match = random.randint(100000, 999999)
                        
                        # Insertion avec l'ID généré
                        supabase.table("Matchs").insert({
                            "id": id_unique_match,
                            "equipe_dom": eq_dom.strip(),
                            "equipe_ext": eq_ext.strip(),
                            "date_match": iso_date,
                            "statut": "NS",
                            "score_dom": None,
                            "score_ext": None
                        }).execute()
                        
                        st.success(f"🎉 Match ajouté avec succès ! ID créé : {id_unique_match}")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur lors de la création : {e}")
                else:
                    st.warning("⚠️ Veuillez remplir le nom des deux équipes.")
    # 9.3 - TAB 3 : GESTION DES MATCHS EXISTANTS
    with tab3:
        st.subheader("📝 Liste et scores des matchs")
        matchs_existants = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data
        
        if matchs_existants:
            for m in matchs_existants:
                with st.container():
                    col_m_info, col_s_dom, col_s_ext, col_stat, col_save = st.columns([3, 1, 1, 2, 1])
                    with col_m_info:
                        st.write(f"**{m['equipe_dom']} - {m['equipe_ext']}**")
                    with col_s_dom:
                        s_d = st.number_input("Dom", min_value=0, value=m.get('score_dom', 0) if m.get('score_dom') is not None else 0, key=f"sd_{m['id']}", step=1)
                    with col_s_ext:
                        s_e = st.number_input("Ext", min_value=0, value=m.get('score_ext', 0) if m.get('score_ext') is not None else 0, key=f"se_{m['id']}", step=1)
                    with col_stat:
                        opt_statut = ["NS", "LIVE", "FT"]
                        idx_statut = opt_statut.index(m['statut']) if m['statut'] in opt_statut else 0
                        st_m = st.selectbox("Statut", opt_statut, index=idx_statut, key=f"stat_{m['id']}")
                    with col_save:
                        if st.button("💾", key=f"save_m_{m['id']}"):
                            try:
                                supabase.table("Matchs").update({
                                    "score_dom": s_d,
                                    "score_ext": s_e,
                                    "statut": st_m
                                }).eq("id", m['id']).execute()
                                st.success("Mis à jour")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e: st.error(str(e))
                    st.markdown("---")

    # 9.4 - TAB 4 : QUESTIONS BONUS
    with tab4:
        st.subheader("🎯 Ajouter une Question Bonus")
        with st.form("ajout_q_form"):
            intitule_q = st.text_input("Intitulé de la question (ex: Qui marquera le premier essai ?)")
            pts_q = st.number_input("Points attribués", min_value=1, value=5, step=1)
            if st.form_submit_button("💾 Enregistrer la question"):
                if intitule_q:
                    try:
                        supabase.table("Questions_Bonus").insert({
                            "question": intitule_q,
                            "points_bonus": pts_q
                        }).execute()
                        st.success("Question ajoutée !")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e: st.error(str(e))

    # 9.5 - TAB 5 : RE-SCRAPING MANUEL
    with tab5:
        st.subheader("🔄 Lanceur de Scraping Manuel")
        if st.button("⚡ Lancer la Synchronisation"):
            with st.spinner("Scraping en cours..."):
                nb = verifier_et_importer_matchs()
                st.success(f"Terminé ! {nb} matchs traités avec succès.")
                st.rerun()

    # 9.6 - TAB 6 : ZONE DE DANGER
    with tab6:
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
                except Exception as e: 
                    st.error(f"Erreur : {e}")
                    st.error(f"Erreur : {e}")
