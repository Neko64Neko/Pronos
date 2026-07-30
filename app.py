import streamlit as st
from supabase import create_client
from datetime import datetime, timedelta, timezone
import requests
import base64
import time
import random
import extra_streamlit_components as stx
import pytz
from streamlit_autorefresh import st_autorefresh
from get_calendar import run_calendar
from get_live import run_update
import urllib.parse

# 1 - PARAMETRES ET CONNEXION
import streamlit.components.v1 as components

# 1.0 - CONVERSION DES DATES
def formater_date_paris(date_iso_str):
    """Convertit une date UTC (Supabase) en heure locale de Paris pour l'affichage."""
    try:
        # On remplace 'Z' par '+00:00' pour que fromisoformat le comprenne comme UTC
        date_clean = date_iso_str.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(date_clean)
        paris_tz = pytz.timezone("Europe/Paris")
        return dt_utc.astimezone(paris_tz).strftime("%d/%m à %H:%M")
    except:
        return date_iso_str

# 1.1 - CONFIGURATION DE LA PAGE
st.set_page_config(page_title="Pronos Top 14", page_icon="🏉", layout="centered")

# 1.2 - CONNEXION À SUPABASE
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1.3 - GESTION DES COOKIES (Stockage simple de l'ID)
# Initialisation des variables pour éviter l'erreur AttributeError
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "pseudo" not in st.session_state:
    st.session_state.pseudo = None
cookie_manager = stx.CookieManager()

# A. Tentative de reconnexion automatique via le cookie ID
if st.session_state.user_id is None:
    saved_user_id = cookie_manager.get(cookie="top14_user_id")
    if saved_user_id:
        # On vérifie si cet ID est toujours valide en base
        try:
            profil = supabase.table("Joueurs").select("is_admin, pseudo").eq("id", saved_user_id).single().execute()
            if profil.data:
                st.session_state.user_id = saved_user_id
                st.session_state.is_admin = profil.data.get("is_admin", False)
                st.session_state.pseudo = profil.data.get("pseudo", "Joueur")
                # Pas besoin de set_session, on gère l'auth manuellement avec cet ID
        except:
            cookie_manager.delete("top14_user_id")

#1.4 - GESTION DES LOGOS
def obtenir_logo(nom_equipe):
    if not nom_equipe:
        return ""
    try:
        nom_propre = nom_equipe.strip()
        reponse = supabase.table("Equipes").select("logo_url").eq("nom", nom_propre).execute()
        
        if reponse.data and len(reponse.data) > 0:
            url = reponse.data[0].get("logo_url")
            if url and url.startswith("http"):
                return url # On renvoie directement l'URL publique Supabase
    except Exception as e:
        print(f"Erreur logo pour '{nom_equipe}' : {e}")
        
    return ""

#1.5 - NOM COURT EQUIPES
#@st.cache_data(ttl=300)
def charger_surnoms_equipes():
    try:
        res = supabase.table("Equipes").select("nom, nom_court").execute()
        if res.data:
            return {item['nom']: item['nom_court'] for item in res.data if item.get('nom_court')}
    except Exception:
        pass
    return {}

# Chargement du dictionnaire des surnoms
dict_surnoms = charger_surnoms_equipes()

def get_nom_affiche(nom):
    """Renvoie le nom court s'il existe, sinon le nom d'origine de l'API"""
    return dict_surnoms.get(nom, nom)

# =====================================================================
# 2 - SYSTEME DE SCRAPING GRATUIT ET AUTOMATIQUE
# =====================================================================
    
    
#2.3 - SAUVEGARDE AUTO PRONO (VERSION SILENCIEUSE)
def sauvegarder_prono_auto(match_id, equipe_dom, equipe_ext, user_id_cible):
    """Sauvegarde instantanément le pronostic en arrière-plan avec une notification discrète."""
    vrai_nom_gagnant = st.session_state.get(f"w_{match_id}_{user_id_cible}")
    ecart = st.session_state.get(f"m_{match_id}_{user_id_cible}")
    
    if (not vrai_nom_gagnant or vrai_nom_gagnant == "...") and (not ecart or ecart == "..."):
        return

    val_gagnant = None
    if vrai_nom_gagnant and vrai_nom_gagnant != "...":
        val_gagnant = "home" if vrai_nom_gagnant == equipe_dom else ("away" if vrai_nom_gagnant == equipe_ext else "draw")
        
    val_ecart = None
    if ecart and ecart != "...":
        val_ecart = ecart
        
    try:
        prono_existant = supabase.table("Pronostics").select("id").eq("user_id", user_id_cible).eq("match_id", match_id).execute().data
        
        donnees_prono = {
            "user_id": user_id_cible, 
            "match_id": match_id, 
            "gagnant_prevu": val_gagnant, 
            "ecart_prevu": val_ecart
        }
        
        if prono_existant:
            supabase.table("Pronostics").update(donnees_prono).eq("id", prono_existant[0]["id"]).execute()
        else:
            supabase.table("Pronostics").insert(donnees_prono).execute()

    except Exception as e:
        st.error(f"Erreur sauvegarde automatique : {e}")
        
#2.4 - Sauvegarde Bonus AUTO
def sauvegarder_bonus_auto(question_id, user_id, valeur_saisie=None):
    """Enregistre automatiquement la réponse bonus d'un joueur."""
    # Si la valeur n'est pas passée directement, on va la chercher dans le widget
    if valeur_saisie is None:
        key_widget = f"q_{question_id}_{user_id}"
        valeur_saisie = st.session_state.get(key_widget, "")
        
    valeur_propre = str(valeur_saisie).strip()
    
    try:
        rep_existante = supabase.table("Réponses_Questions").select("*").eq("user_id", user_id).eq("question_id", question_id).execute().data
        
        if rep_existante:
            supabase.table("Réponses_Questions").update({"reponse_joueur": valeur_propre}).eq("id", rep_existante[0]['id']).execute()
        else:
            supabase.table("Réponses_Questions").insert({"user_id": user_id, "question_id": question_id, "reponse_joueur": valeur_propre}).execute()
    except Exception as e:
        st.error(f"Erreur lors de l'enregistrement automatique : {e}")
        
# =====================================================================
# 3 - INITIALISATION ET GESTION DE LA SESSION
# =====================================================================
if "user_id" not in st.session_state: st.session_state.user_id = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "pseudo" not in st.session_state: st.session_state.pseudo = ""
if "onglet_actif" not in st.session_state: st.session_state.onglet_actif = "📊"

TRANCHES_ECARTS = ["1-6", "7-10", "11-15", "16-20", "21-30", "31-40", "41-50", "51+"]
maintenant_paris = datetime.utcnow() + timedelta(hours=2)

# =====================================================================
# 4 - ÉCRAN DE CONNEXION / INSCRIPTION
# =====================================================================
if st.session_state.user_id is None:
    st.title("🏉 Pronos Top 14")
    onglet_connexion = st.tabs(["Se connecter", "S'inscrire", "Mot de passe oublié"])
    
    with onglet_connexion[0]:
        email = st.text_input("Email", key="login_email")
        mdp = st.text_input("Mot de passe", type="password", key="login_pass")
        
        if st.button("Se connecter"):
            try:
                # 1. Tentative de connexion
                res = supabase.auth.sign_in_with_password({
                    "email": email.strip().lower(), 
                    "password": mdp.strip()
                })
                
                # 2. Récupération du profil
                profil = supabase.table("Joueurs").select("is_admin, pseudo").eq("id", res.user.id).single().execute()
                
                # 3. Sauvegarde de la session en mémoire
                st.session_state.user_id = res.user.id
                st.session_state.is_admin = profil.data.get("is_admin", False)
                st.session_state.pseudo = profil.data.get("pseudo", "Joueur")
                
                # 4. Sauvegarde de l'ID dans le cookie (Reconnexion automatique)
                cookie_manager.set("top14_user_id", res.user.id, max_age=30*24*3600)
                
                st.success(f"Ravi de vous revoir {st.session_state.pseudo} !")
                time.sleep(0.5)
                st.rerun()
                
            except Exception as e:
                st.error("Identifiants incorrects.")

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
        options_menu = ["📊", "🏉", "📺", "⚙️"]
        labels_menu = {
            "📊": "📊 Général",
            "🏉": "🏉 Pronos",
            "📺": "📺 Résultats",
            "⚙️": "⚙️ Admin"
        }
    else:
        options_menu = ["📊", "🏉", "📺"]
        labels_menu = {
            "📊": "📊 Général",
            "🏉": "🏉 Pronos",
            "📺": "📺 Résultats"
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
        response = supabase.table("Configuration").select("*").eq("id", "default_config").single().execute()
        if response.data:
            conf = response.data
            # On écrase le session_state avec ce qui vient de la base
            st.session_state.pts_vainqueur = conf.get("pts_gagnant", 1)
            st.session_state.pts_ecart = conf.get("pts_ecart", 2)
            st.session_state.pct_ose = conf.get("seuil_poursentage_ose", 3)
            st.session_state.pts_v_ose = conf.get("pts_vainqueur_ose", 2)
            st.session_state.pts_e_ose = conf.get("pts_ecart_ose", 3)
            
            st.sidebar.success("Configuration chargée depuis Supabase") # Petit feedback visuel
    except Exception as e:
        st.error(f"Erreur de chargement : {e}")

# =====================================================================
# 6 - CONTENU DE L'ONGLET 1 : CLASSEMENT GÉNÉRAL (LOGIQUE ET CLASSEMENT LIVE)
# =====================================================================
    if st.session_state.onglet_actif == "📊":
        st.markdown(f"### 🏉 Bienvenue sur ton tableau de bord, **{st.session_state.pseudo}** !")
        
        # --- RÉCUPÉRATION DYNAMIQUE DE LA CONFIGURATION SUPABASE ---
        try:
            pts_gagnant_cfg = float(st.session_state.get("pts_vainqueur", 1))
            pts_ecart_cfg = float(st.session_state.get("pts_ecart", 2))
            seuil_ose_cfg = int(st.session_state.get("pct_ose", 3))
            pts_v_ose_cfg = float(st.session_state.get("pts_v_ose", 2))
            pts_e_ose_cfg = float(st.session_state.get("pts_e_ose", 3))
        except Exception as e:
            pts_gagnant_cfg = 1.0
            pts_ecart_cfg = 2.0
            seuil_ose_cfg = 3
            pts_v_ose_cfg = 2.0
            pts_e_ose_cfg = 3.0
         
        try:
            tous_les_joueurs = supabase.table("Joueurs").select("*").execute().data
            pronostics_tous = supabase.table("Pronostics").select("*").execute().data
            matchs_comptabilises = supabase.table("Matchs").select("*").in_("statut", ["FT", "LIVE"]).execute().data
            questions_bonus = supabase.table("Questions_Bonus").select("*").execute().data
            reponses_bonus = supabase.table("Réponses_Questions").select("*").execute().data

            dict_matchs = {m['id']: m for m in matchs_comptabilises}
            dict_reponses_bonus = {(r['user_id'], r['question_id']): r.get('reponse_joueur', '').strip().lower() for r in reponses_bonus}
            dict_points_bonus = {q['id']: (q.get('points_bonus') or q.get('points') or 0, str(q.get('reponse_correcte') or '').strip().lower()) for q in questions_bonus}

            scores_calculateurs = {}
            for j in tous_les_joueurs:
                pts_manuels = float(j.get('points_manuels', 0) or 0)
                scores_calculateurs[j['id']] = {
                    "id": j['id'],
                    "pseudo": j['pseudo'],
                    "score_live": pts_manuels,  # Initialisé avec les points manuels pour impacter le classement
                    "points_manuels": pts_manuels,
                    "vainqueurs": 0,
                    "ecarts": 0,
                    "bonus": 0
                }

            # 3. Calcul des points sur les matchs (FT + LIVE)
            for p in pronostics_tous:
                j_id = p['user_id']
                m_id = p['match_id']
                 
                if j_id not in scores_calculateurs or m_id not in dict_matchs:
                    continue
                     
                match = dict_matchs[m_id]
                sc_dom = match.get('score_dom')
                sc_ext = match.get('score_ext')
                 
                if sc_dom is None or sc_ext is None:
                    continue
                     
                vrai_gagnant = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                vrai_ecart_points = abs(sc_dom - sc_ext)
                 
                if vrai_ecart_points <= 6: vraie_tranche = "1-6"
                elif vrai_ecart_points <= 10: vraie_tranche = "7-10"
                elif vrai_ecart_points <= 15: vraie_tranche = "11-15"
                elif vrai_ecart_points <= 20: vraie_tranche = "16-20"
                elif vrai_ecart_points <= 30: vraie_tranche = "21-30"
                elif vrai_ecart_points <= 40: vraie_tranche = "31-40"
                elif vrai_ecart_points <= 50: vraie_tranche = "41-50"
                else: vraie_tranche = "51+"

                pronos_ce_match = [pr for pr in pronostics_tous if pr['match_id'] == m_id]
                 
                def est_un_nul(val):
                    if not val:
                        return False
                    val_str = str(val).strip().lower()
                    return val_str in ["draw", "match nul", "nul", "n", "x", "egalite", "égalité"]
        
                vrai_est_nul = est_un_nul(vrai_gagnant)
                
                if not vrai_est_nul and 'score_dom' in match and 'score_ext' in match:
                    if match['score_dom'] is not None and match['score_ext'] is not None and match['score_dom'] == match['score_ext']:
                        vrai_est_nul = True
        
                mises_gagnant = sum(
                    1 for pr in pronos_ce_match 
                    if (vrai_est_nul and est_un_nul(pr.get('gagnant_prevu'))) or (not vrai_est_nul and pr.get('gagnant_prevu') == vrai_gagnant)
                )
                 
                points_ce_match = 0.0
                 
                p_gagnant = p.get('gagnant_prevu')
                p_est_nul = est_un_nul(p_gagnant)
                a_bon_vainqueur = (vrai_est_nul and p_est_nul) or (not vrai_est_nul and p_gagnant == vrai_gagnant)
        
                if a_bon_vainqueur:
                    a_bon_ecart = True if vrai_est_nul else (p.get('ecart_prevu') == vraie_tranche)
        
                    if mises_gagnant <= int(float(seuil_ose_cfg)):
                        points_ce_match += float(pts_gagnant_cfg) + float(pts_v_ose_cfg)
                        if a_bon_ecart:
                            points_ce_match += float(pts_ecart_cfg) + float(pts_e_ose_cfg)
                    else:
                        points_ce_match += float(pts_gagnant_cfg)
                        if a_bon_ecart:
                            points_ce_match += float(pts_ecart_cfg)
        
                    scores_calculateurs[j_id]["score_live"] += points_ce_match
                    
                    # Comptabilisation des stats persos du joueur connecté (ou globalement si besoin)
                    if j_id == st.session_state.user_id:
                        scores_calculateurs[j_id]["vainqueurs"] += 1
                        if a_bon_ecart:
                            scores_calculateurs[j_id]["ecarts"] += 1

        # 4. Calcul des points Questions Bonus
            for (j_id, q_id), rep_joueur in dict_reponses_bonus.items():
                if j_id in scores_calculateurs and q_id in dict_points_bonus:
                    pts_config, rep_officielle = dict_points_bonus[q_id]
                    
                    rep_joueur_clean = str(rep_joueur).strip().lower() if rep_joueur else ""
                    rep_officielle_clean = str(rep_officielle).strip().lower() if rep_officielle else ""
                    
                    if rep_officielle_clean and rep_joueur_clean == rep_officielle_clean:
                        pts_attribues = 0
                        pts_config_str = str(pts_config).strip().lower()
                        
                        if ":" in pts_config_str:
                            segments = pts_config_str.split(";")
                            for s in segments:
                                if ":" in s:
                                    cle_rep, val_pts = s.split(":")
                                    if rep_officielle_clean == cle_rep.strip().lower():
                                        try:
                                            pts_attribues = float(val_pts.strip())
                                        except ValueError:
                                            pts_attribues = 0
                                        break
                        else:
                            try:
                                pts_attribues = float(pts_config_str)
                            except ValueError:
                                pts_attribues = 0

                        if pts_attribues > 0:
                            scores_calculateurs[j_id]["score_live"] += pts_attribues
                            scores_calculateurs[j_id]["bonus"] += pts_attribues

            # 5. Tri pour générer le classement dynamique
            tous_les_joueurs_ordonnes = list(scores_calculateurs.values())
            tous_les_joueurs_ordonnes.sort(key=lambda x: x["score_live"], reverse=True)

            stats_joueur_connecte = scores_calculateurs.get(st.session_state.user_id, {"score_live": 0, "points_manuels": 0, "vainqueurs": 0, "ecarts": 0})
            
            # Recalcul précis des matchs osés réussis uniquement pour l'affichage des compteurs du joueur connecté
            stats_oses = 0
            pronos_joueur = [p for p in pronostics_tous if p['user_id'] == st.session_state.user_id]
            for p in pronos_joueur:
                m_id = p['match_id']
                if m_id in dict_matchs:
                    match = dict_matchs[m_id]
                    sd, se = match.get('score_dom'), match.get('score_ext')
                    if sd is not None and se is not None:
                        vg = "home" if sd > se else ("away" if sd < se else "draw")
                        vrai_ecart_points = abs(sd - se)
                        if vrai_ecart_points <= 6: vraie_tranche_m = "1-6"
                        elif vrai_ecart_points <= 10: vraie_tranche_m = "7-10"
                        elif vrai_ecart_points <= 15: vraie_tranche_m = "11-15"
                        elif vrai_ecart_points <= 20: vraie_tranche_m = "16-20"
                        elif vrai_ecart_points <= 30: vraie_tranche_m = "21-30"
                        elif vrai_ecart_points <= 40: vraie_tranche_m = "31-40"
                        elif vrai_ecart_points <= 50: vraie_tranche_m = "41-50"
                        else: vraie_tranche_m = "51+"
                        
                        if p['gagnant_prevu'] == vg:
                            pronos_m = [pr for pr in pronostics_tous if pr['match_id'] == m_id]
                            nb_gagnants = sum(1 for pm in pronos_m if pm['gagnant_prevu'] == vg)
                            
                            if nb_gagnants < seuil_ose_cfg:
                                stats_oses += 1
                                if p['ecart_prevu'] == vraie_tranche_m and vg != "draw":
                                    stats_oses += 1

            rang_joueur = "-"
            for idx, j in enumerate(tous_les_joueurs_ordonnes):
                if j['id'] == st.session_state.user_id:
                    rang_joueur = idx + 1
                    break

        except Exception as e:
            st.error(f"Erreur de calcul du classement en direct : {e}")
            tous_les_joueurs_ordonnes = []
            rang_joueur = "-"
            stats_joueur_connecte = {"score_live": 0, "points_manuels": 0, "vainqueurs": 0, "ecarts": 0}
            stats_oses = 0

        suffixe = "er" if rang_joueur == 1 else "e"
        score_affiche = stats_joueur_connecte["score_live"]
        score_affiche = int(score_affiche) if isinstance(score_affiche, float) and score_affiche.is_integer() else score_affiche
        
        # --- BLOC DES COMPTEURS VISUELS DE L'UTILISATEUR ---
        st.markdown(f"""
        <div style="background-color: #f0f4f8; border-radius: 16px; padding: 15px; border: 1px solid #d3e2f2; margin-bottom: 25px;">
            <div style="display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 90px; max-width: 110px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #627d98; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🏆 Rang</span>
                    <span style="color:#1e3a8a; font-size: 26px; font-weight: 900;">{rang_joueur}{suffixe}</span>
                    <span style="display:block; font-size:10px; color:#627d98;">/{len(tous_les_joueurs_ordonnes)}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 90px; max-width: 110px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #627d98; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🎯 Points </span>
                    <span style="color:#1e3a8a; font-size: 26px; font-weight: 900;">{score_affiche}</span>
                    <span style="display:block; font-size:10px; color:#627d98;">pts</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #43a047; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">✅ Vainqueurs</span>
                    <span style="color: #43a047; font-size: 32px; font-weight: 900;">{stats_joueur_connecte["vainqueurs"]}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #0a3613; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">⭐ Bon Écart</span>
                    <span style="color: #0a3613; font-size: 32px; font-weight: 900;">{stats_joueur_connecte["ecarts"]}</span>
                </div>
                <div style="background-color: #ffffff; border-radius: 10px; padding: 8px; min-width: 100px; max-width: 120px; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                    <span style="color: #b7791f; font-size: 11px; font-weight: bold; display:block; margin-bottom:2px;">🔥 Osés</span>
                    <span style="color: #b7791f; font-size: 32px; font-weight: 900;">{stats_oses}</span>
                </div>
            </div>
        </div>
        """.replace("\n", ""), unsafe_allow_html=True)

        # --- TABLEAU DU CLASSEMENT GÉNÉRAL GÉNÉRÉ EN DIRECT ---
        st.subheader(" 🏆 Classement")
        if tous_les_joueurs_ordonnes:
            lignes_html = ""
            for index, joueur in enumerate(tous_les_joueurs_ordonnes):
                rang = index + 1
                prefixe_rang = "🥇 1er" if rang == 1 else ("🥈 2e" if rang == 2 else ("🥉 3e" if rang == 3 else f"{rang}e"))
                
                if joueur['id'] == st.session_state.user_id:
                    style_ligne = "background-color: #cbd5e1; font-weight: bold; border-left: 5px solid #1e3a8a; color: #000000;"
                    pseudo_affiche = f"{joueur['pseudo']} "
                else:
                    style_ligne = "color: #2d3748;"
                    pseudo_affiche = joueur['pseudo']
                
                sc_j = joueur["score_live"]
                pts_m = int(joueur["points_manuels"] or 0)  # <-- Conversion explicite en int ici
                sc_j_affiche = int(sc_j) if isinstance(sc_j, float) and sc_j.is_integer() else sc_j
                
                # Affichage combiné du score et des points manuels si présents
                if pts_m != 0:
                    pts_m_str = f" ({pts_m:+d} 🎁)"
                    points_cellule = f"<b>{sc_j_affiche}</b> <span style='font-size: 11px; color: #d97706; font-weight: normal;'>{pts_m_str}</span>"
                else:
                    points_cellule = f"<b>{sc_j_affiche}</b>"
                
                lignes_html += f'<tr style="{style_ligne} border-bottom: 1px solid #e2e8f0;"><td style="padding: 12px; text-align: right; color: inherit;">{prefixe_rang}</td><td style="padding: 12px; text-align: left; color: inherit;">{pseudo_affiche}</td><td style="padding: 12px; text-align: center; color: #000000;">{points_cellule}</td></tr>'
            
            st.markdown(f"""
            <div style="background-color: #f8fafc; border-radius: 12px; padding: 15px; border: 1px solid #e2e8f0;">
                <table style="width: 100%; border-collapse: collapse; font-family: sans-serif; color: #2d3748;">
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
# 7.2.1 - SECTION QUESTIONS BONUS AVEC BLOCAGE TEMPOREL & SELECTBOX
                    st.subheader("🎯 Questions Bonus")
                    questions = supabase.table("Questions_Bonus").select("*").eq("statut", "open").execute().data
                    
                    # Droits admin totaux (sidebar + onglet prono activés)
                    droits_admin_totalement_actifs = (
                        st.session_state.is_admin 
                        and st.session_state.get('mode_admin_actif', False) 
                        and st.session_state.get('mode_admin_pronos', False)
                    )

                    if questions:
                        for q in questions:
                            # Vérification de la date limite avec gestion propre du fuseau horaire
                            question_bloquee = False
                            date_limite_str = q.get('date_limite')
                            
                            if date_limite_str:
                                try:
                                    # 1. On parse la date de Supabase et on extrait l'heure "brute" calculée à Paris
                                    if date_limite_str.endswith('Z'):
                                        date_limite_str = date_limite_str[:-1] + '+00:00'
                                    dt_limite_utc = datetime.fromisoformat(date_limite_str)
                                    
                                    tz_paris = pytz.timezone('Europe/Paris')
                                    dt_limite_q = dt_limite_utc.astimezone(tz_paris)
                                    
                                    # 2. STRIP DES FUSEAUX (On rend les deux dates "naïves" pour la comparaison)
                                    # On extrait juste l'année, mois, jour, heure, minute sans l'étiquette de fuseau
                                    limite_naive = dt_limite_q.replace(tzinfo=None)
                                    maintenant_naif = maintenant_paris.replace(tzinfo=None)
                                    
                                    # 3. Comparaison brute sécurisée
                                    if maintenant_naif >= limite_naive:
                                        if droits_admin_totalement_actifs:
                                            st.markdown(f"<div style='color: #b7791f; font-size: 0.85em; font-weight: bold;'>⚠️ Temps écoulé ({dt_limite_q.strftime('%d/%m/%Y à %H:%M')}) - Saisie Admin Autorisée</div>", unsafe_allow_html=True)
                                        else:
                                            st.markdown(f"<div style='color: #dc2626; font-size: 0.85em; font-weight: bold;'>🔒 Réponses fermées depuis le {formater_date_paris(date_limite_str)}</div>", unsafe_allow_html=True)
                                            question_bloquee = True
                                    else:
                                        st.markdown(f"<div style='color: #64748b; font-size: 0.85em;'>⏳ Limite : {dt_limite_q.strftime('%d/%m/%Y à %H:%M')}</div>", unsafe_allow_html=True)
                                except Exception as e:
                                    st.caption(f"Erreur date : {e}")

                            # Récupération de la réponse existante du joueur cible
                            rep_existante = supabase.table("Réponses_Questions").select("*").eq("user_id", id_joueur_cible).eq("question_id", q['id']).execute().data
                            valeur_defaut = rep_existante[0]['reponse_joueur'] if rep_existante and rep_existante[0].get('reponse_joueur') is not None else ""
                            
                            texte_question = q.get('question') or "Question Bonus"
                            pts_bonus = q.get('points') or q.get('points_bonus') or 0
                            
                            # Extraction des options possibles pour créer le selectbox
                            pts_config_str = str(pts_bonus).strip()
                            options_joueur = []
                            
                            if ":" in pts_config_str:
                                segments = pts_config_str.split(";")
                                html_bareme = "<div style='display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 5px;'>"
                                for s in segments:
                                    if ":" in s:
                                        choix, pts = s.split(":")
                                        nom_option = choix.strip()
                                        options_joueur.append(nom_option)
                                        html_bareme += f'<span style="background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 0.75em; color: #1e3a8a;"><b>{nom_option}</b> : +{pts.strip()} pts</span>'
                                html_bareme += "</div>"
                                st.markdown(html_bareme, unsafe_allow_html=True)
                                label_input = f"❓ {texte_question}"
                            else:
                                label_input = f"❓ {texte_question} ({pts_bonus} pts)"

                            # --- SÉLECTION DU COMPORTEMENT GRAPHIQUE (LISTE DÉROULANTE VS TEXTE) ---
                            nouvelle_rep = valeur_defaut
                            
                            if options_joueur:
                                # Création des options avec une valeur neutre
                                options_formatees = ["-- Choisir une option --"] + options_joueur
                                
                                # Détermination de l'index si une réponse existe déjà (insensible à la casse)
                                index_actuel = 0
                                if valeur_defaut:
                                    for idx, opt in enumerate(options_formatees):
                                        if opt.lower().strip() == valeur_defaut.lower().strip():
                                            index_actuel = idx
                                            break
                                
                                choix_selectbox = st.selectbox(
                                    label_input,
                                    options=options_formatees,
                                    index=index_actuel,
                                    key=f"q_{q['id']}_{id_joueur_cible}",
                                    disabled=question_bloquee
                                )
                                
                                if choix_selectbox == "-- Choisir une option --":
                                    nouvelle_rep = ""
                                else:
                                    nouvelle_rep = choix_selectbox
                            else:
                                # Mode de secours (Point unique) : Saisie textuelle classique
                                nouvelle_rep = st.text_input(
                                    label_input,
                                    value=valeur_defaut,
                                    key=f"q_txt_{q['id']}_{id_joueur_cible}",
                                    disabled=question_bloquee,
                                    placeholder="Écris ta réponse ici..."
                                )

                            # Déclenchement manuel contrôlé de la sauvegarde automatique en cas de changement
                            if nouvelle_rep != valeur_defaut:
                                sauvegarder_bonus_auto(q['id'], id_joueur_cible, nouvelle_rep)
                                st.rerun()

                            st.markdown("<br>", unsafe_allow_html=True)
                    else:
                        st.caption("Aucune question bonus pour le moment.")
                except Exception as e:
                    st.error(f"Erreur lors du chargement des questions bonus : {e}")

            # 7.2.2 - SECTION MATCHS OUVERTS
                st.markdown('<div style="height: 1px; background-color: #cbd5e1; margin: 25px auto 15px auto; width: calc(100% - 40px);"></div>', unsafe_allow_html=True)
                st.subheader("🏉 Liste des Matchs")
            
                # CSS global inchangé
                st.markdown("""
                    <style>
                        [data-testid="stVerticalBlockBorderWrapper"] {
                            border: 1.5px solid #cbd5e1 !important;
                            border-radius: 12px !important;
                            padding-bottom: 14px !important;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
                        }
                        div.stButton > button {
                            border-radius: 25px !important;
                            width: 100% !important;
                            height: 46px !important;
                            min-height: 46px !important;
                            max-height: 46px !important;
                            font-weight: 600 !important;
                            font-size: 0.9em !important;
                            padding: 0 12px !important;
                            box-sizing: border-box !important;
                            white-space: nowrap !important;
                            overflow: hidden !important;
                            text-overflow: ellipsis !important;
                            display: flex !important;
                            align-items: center !important;
                            justify-content: center !important;
                            margin-bottom: 6px !important;
                        }
                        hr.match-separator {
                            border: none !important;
                            border-top: 1px solid #cbd5e1 !important;
                            border-bottom: 1px solid #cbd5e1 !important;
                            height: 3px !important;
                            width: 40% !important;
                            margin: 30px auto !important;
                            background-color: transparent !important;
                        }
                    </style>
                """, unsafe_allow_html=True)
            
                # Mise en cache pour accélérer le chargement initial
                @st.cache_data(ttl=3600)
                def logo_cache(equipe):
                    return obtenir_logo(equipe)
            
                @st.cache_data(ttl=3600)
                def nom_affiche_cache(equipe):
                    return get_nom_affiche(equipe)
            
                try:
                    matchs_potentiels = supabase.table("Matchs").select("*").neq("statut", "FT").execute().data
                    matchs_visibles = []
                    
                    droits_admin_totalement_actifs = (
                        st.session_state.is_admin 
                        and st.session_state.get('mode_admin_actif', False) 
                        and st.session_state.get('mode_admin_pronos', False)
                    )
                    
                    paris_tz = pytz.timezone("Europe/Paris")
                    
                    if matchs_potentiels:
                        for m in matchs_potentiels:
                            try:
                                date_clean = m['date_match'].replace("Z", "+00:00")
                                dt_match_utc = datetime.fromisoformat(date_clean)
                                dt_match_paris = dt_match_utc.astimezone(paris_tz)
                                
                                if maintenant_paris.replace(tzinfo=None) < dt_match_paris.replace(tzinfo=None) or droits_admin_totalement_actifs:
                                    matchs_visibles.append(m)
                            except Exception:
                                if m['statut'] == "NS" or droits_admin_totalement_actifs:
                                    matchs_visibles.append(m)
            
                    if matchs_visibles:
                        matchs_visibles = sorted(matchs_visibles, key=lambda x: x['date_match'] if x.get('date_match') is not None else "9999-12-31")
                        
                        tous_pronos_bruts = supabase.table("Pronostics").select("*").eq("user_id", id_joueur_cible).execute().data
                        dict_tous_pronos = {p['match_id']: p for p in tous_pronos_bruts} if tous_pronos_bruts else {}
                        
                        # --- FRAGMENT ULTRA-RAPIDE PAR MATCH ---
                        @st.fragment
                        def afficher_carte_match(m, id_joueur_cible, dict_tous_pronos_local, droits_admin_actifs, maintenant_paris_local, paris_tz_local):
                            with st.container(border=True):
                                logo_dom = logo_cache(m["equipe_dom"])
                                logo_ext = logo_cache(m["equipe_ext"])
                                
                                nom_dom_affiche = nom_affiche_cache(m["equipe_dom"])
                                nom_ext_affiche = nom_affiche_cache(m["equipe_ext"])
                                
                                logo_dom_html = f'<img src="{logo_dom}" style="width: 32px; height: 32px; object-fit: contain; vertical-align: middle; flex-shrink: 0;">' if logo_dom else ''
                                logo_ext_html = f'<img src="{logo_ext}" style="width: 32px; height: 32px; object-fit: contain; vertical-align: middle; flex-shrink: 0;">' if logo_ext else ''
                                
                                header_html = f"""
                                <div style="display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 6px; text-align: center;">
                                    <div style="display: flex; align-items: center; gap: 8px; justify-content: flex-end; flex: 1;">
                                        {logo_dom_html}
                                        <span style="font-weight: bold; font-size: 1.1em; color: #2563eb; white-space: normal; word-break: break-word; text-align: right;" title="{m["equipe_dom"]}">{nom_dom_affiche}</span>
                                    </div>
                                    <span style="color: #94a3b8; font-size: 1.1em; font-weight: 500; padding: 0 2px; flex-shrink: 0;">vs</span>
                                    <div style="display: flex; align-items: center; gap: 8px; justify-content: flex-start; flex: 1;">
                                        <span style="font-weight: bold; font-size: 1.1em; color: #2563eb; white-space: normal; word-break: break-word; text-align: left;" title="{m["equipe_ext"]}">{nom_ext_affiche}</span>
                                        {logo_ext_html}
                                    </div>
                                </div>
                                """
                                st.markdown(header_html, unsafe_allow_html=True)
                                
                                bouton_bloque = False
                                try:
                                    date_clean = m['date_match'].replace("Z", "+00:00")
                                    dt_match_utc = datetime.fromisoformat(date_clean)
                                    dt_match_paris = dt_match_utc.astimezone(paris_tz_local)
                                    
                                    date_affiche = formater_date_paris(m['date_match'])
                                    match_commence = maintenant_paris_local.replace(tzinfo=None) >= dt_match_paris.replace(tzinfo=None)
                                    
                                    if match_commence:
                                        if droits_admin_actifs:
                                            st.markdown(f"<div style='text-align: center; color: #b7791f; font-size: 0.9em; font-weight: bold; margin-bottom: 10px;'>⚠️ Match commencé ({date_affiche}) - Autorisé (Admin)</div>", unsafe_allow_html=True)
                                        else:
                                            st.markdown(f"<div style='text-align: center; color: #dc2626; font-size: 0.9em; font-weight: bold; margin-bottom: 10px;'>🔒 Match commencé le {date_affiche}</div>", unsafe_allow_html=True)
                                            bouton_bloque = True
                                    else:
                                        st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.9em; margin-bottom: 10px;'>📅 Match prévu le {date_affiche}</div>", unsafe_allow_html=True)
                                except Exception:
                                    pass
            
                                prono_donnees = dict_tous_pronos_local.get(m['id'])
                                choix_actuel = None
                                ecart_existant = "..."
                                
                                if prono_donnees:
                                    g_prevu = prono_donnees['gagnant_prevu']
                                    if g_prevu == "home": choix_actuel = m['equipe_dom']
                                    elif g_prevu == "away": choix_actuel = m['equipe_ext']
                                    elif g_prevu == "draw": choix_actuel = "Match Nul"
                                    
                                    if prono_donnees.get('ecart_prevu'):
                                        ecart_existant = prono_donnees['ecart_prevu']
                                
                                key_w = f"w_{m['id']}_{id_joueur_cible}"
                                if key_w not in st.session_state:
                                    st.session_state[key_w] = choix_actuel
                                else:
                                    choix_actuel = st.session_state[key_w]
            
                                def cb_changement_ecart(match_id, eq_dom, eq_ext, u_id):
                                    sauvegarder_prono_auto(match_id, eq_dom, eq_ext, u_id)
            
                                st.markdown('<div style="font-size: 1.1em; font-weight: 600; color: #64748b; margin-bottom: 6px; text-align: center;">Sélectionner le Vainqueur :</div>', unsafe_allow_html=True)
                                
                                is_dom_sel = (choix_actuel == m['equipe_dom'])
                                is_nul_sel = (choix_actuel == "Match Nul")
                                is_ext_sel = (choix_actuel == m['equipe_ext'])
            
                                # AVEC ST.RERUN() POUR RAFRAÎCHIR L'AFFICHAGE INSTANTANÉMENT DÈS LE 1er CLIC
                                if st.button(nom_dom_affiche, key=f"btn_dom_{m['id']}", type="primary" if is_dom_sel else "secondary", disabled=bouton_bloque, use_container_width=True):
                                    st.session_state[key_w] = m['equipe_dom']
                                    sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                    st.rerun()
            
                                if st.button("🤝 Match Nul", key=f"btn_nul_{m['id']}", type="primary" if is_nul_sel else "secondary", disabled=bouton_bloque, use_container_width=True):
                                    st.session_state[key_w] = "Match Nul"
                                    sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                    st.rerun()
            
                                if st.button(nom_ext_affiche, key=f"btn_ext_{m['id']}", type="primary" if is_ext_sel else "secondary", disabled=bouton_bloque, use_container_width=True):
                                    st.session_state[key_w] = m['equipe_ext']
                                    sauvegarder_prono_auto(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible)
                                    st.rerun()
            
                                st.markdown("<br>", unsafe_allow_html=True)
                                
                                key_m = f"m_{m['id']}_{id_joueur_cible}"
                                options_ecarts = ["..."] + TRANCHES_ECARTS
                                
                                if key_m not in st.session_state:
                                    st.session_state[key_m] = ecart_existant if ecart_existant in TRANCHES_ECARTS else "..."
            
                                val_vainqueur = st.session_state.get(key_w, choix_actuel)
                                est_match_nul = (val_vainqueur == "Match Nul")
            
                                if est_match_nul:
                                    st.markdown('<div style="font-size: 1.1em; font-weight: 600; color: #94a3b8; margin-bottom: 2px;">Écart (pts) : <span style="font-size: 0.85em; font-weight: normal; font-style: italic;">(Non requis pour un match nul)</span></div>', unsafe_allow_html=True)
                                else:
                                    st.markdown('<div style="font-size: 1.1em; font-weight: 600; color: #64748b; margin-bottom: 2px;">Écart (pts) :</div>', unsafe_allow_html=True)
                                
                                st.selectbox(
                                    "Écart (pts)", 
                                    options=options_ecarts,
                                    key=key_m, 
                                    on_change=cb_changement_ecart, 
                                    args=(m['id'], m['equipe_dom'], m['equipe_ext'], id_joueur_cible),
                                    disabled=bouton_bloque or est_match_nul,
                                    label_visibility="collapsed"
                                )
                                
                                val_ecart = st.session_state.get(key_m, ecart_existant)
                                has_vainqueur = bool(val_vainqueur and val_vainqueur != "")
                                
                                if est_match_nul:
                                    has_ecart = True
                                else:
                                    has_ecart = bool(val_ecart and val_ecart != "...")
                                
                                if has_vainqueur and has_ecart:
                                    st.markdown(
                                        "<div style='background-color: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; padding: 10px; border-radius: 8px; font-size: 0.9em; font-weight: bold; margin-top: 15px; text-align: center;'>"
                                        "✅ Pronostic complet enregistré"
                                        "</div>", 
                                        unsafe_allow_html=True
                                    )
                                elif has_vainqueur and not has_ecart:
                                    st.markdown(
                                        "<div style='background-color: #fffbeb; border: 1px solid #fde68a; color: #92400e; padding: 10px; border-radius: 8px; font-size: 0.9em; font-weight: bold; margin-top: 15px; text-align: center;'>"
                                        "⚠️ Vainqueur enregistré, n'oubliez pas l'écart"
                                        "</div>", 
                                        unsafe_allow_html=True
                                    )
                                elif not has_vainqueur and has_ecart:
                                    st.markdown(
                                        "<div style='background-color: #fffbeb; border: 1px solid #fde68a; color: #92400e; padding: 10px; border-radius: 8px; font-size: 0.9em; font-weight: bold; margin-top: 15px; text-align: center;'>"
                                        "⚠️ Écart enregistré, n'oubliez pas le vainqueur"
                                        "</div>", 
                                        unsafe_allow_html=True
                                    )
            
                        # --- BOUCLE D'AFFICHAGE DES MATCHS ---
                        total_matchs = len(matchs_visibles)
                        for index, m in enumerate(matchs_visibles):
                            afficher_carte_match(m, id_joueur_cible, dict_tous_pronos, droits_admin_totalement_actifs, maintenant_paris, paris_tz)
                            
                            if index < total_matchs - 1:
                                st.markdown('<hr class="match-separator">', unsafe_allow_html=True)
                    else: 
                        st.info("Aucun match disponible à pronostiquer.")
                except Exception as e: 
                    st.error(f"Erreur lors du chargement de la grille : {e}")
        else:
            st.error("Impossible de récupérer les informations du joueur sélectionné.")
    else:
        st.warning("⚠️ Aucun joueur trouvé dans la base.")

# =====================================================================
# 8 - CONTENU DE L'ONGLET 3 : RÉSULTATS & DIRECT (AVEC MATCHS LIVE)
# =====================================================================
elif st.session_state.onglet_actif == "📺":
    st.title("📺 Résultats & Matchs en Direct")

    # --- RÉCUPÉRATION DYNAMIQUE DE LA CONFIGURATION SUPABASE ---
    try:
        config_supabase = supabase.table("Configuration").select("*").execute().data
        config_data = config_supabase[0] if config_supabase else {}
        pts_gagnant_cfg = float(config_data.get('pts_gagnant', 2))
        pts_ecart_cfg = float(config_data.get('pts_ecart', 3))
        seuil_ose_cfg = float(config_data.get('seuil_poursentage_ose', 3))
        pts_v_ose_cfg = float(config_data.get('pts_vainqueur_ose', 2))
        pts_e_ose_cfg = float(config_data.get('pts_ecart_ose', 3))
    except Exception:
        pts_gagnant_cfg = 2.0
        pts_ecart_cfg = 3.0
        seuil_ose_cfg = 3.0
        pts_v_ose_cfg = 2.0
        pts_e_ose_cfg = 3.0
    
    with st.spinner("Mise à jour des scores et du classement..."):
        try:
            tous_les_joueurs = supabase.table("Joueurs").select("*").execute().data or []
            tous_matchs_bdd = supabase.table("Matchs").select("*").order("date_match", desc=True).execute().data or []
            tous_les_pronos = supabase.table("Pronostics").select("*").execute().data or []
            questions_bonus = supabase.table("Questions_Bonus").select("*").execute().data or []
            reponses_bonus = supabase.table("Réponses_Questions").select("*").execute().data or []
            tous_equipes = supabase.table("Equipes").select("*").execute().data or []
            
            # --- DICTIONNAIRES DE CORRESPONDANCE (LOGO_URL CIBLÉ) ---
            dict_noms_courts = {}
            dict_logos = {}
            for eq in tous_equipes:
                nom_api = eq.get('nom') or eq.get('nom_api')
                if nom_api:
                    clean_key = str(nom_api).strip().lower()
                    dict_noms_courts[clean_key] = eq.get('nom_court', nom_api)
                    dict_logos[clean_key] = eq.get('logo_url', '')
            
            paris_tz = pytz.timezone("Europe/Paris")
            
            matchs = []
            if tous_matchs_bdd:
                for m in tous_matchs_bdd:
                    try:
                        date_clean = m['date_match'].replace("Z", "+00:00")
                        dt_match_utc = datetime.fromisoformat(date_clean)
                        dt_match_paris = dt_match_utc.astimezone(paris_tz)
                        
                        if m['statut'] in ["FT", "LIVE"] or maintenant_paris.replace(tzinfo=None) >= dt_match_paris.replace(tzinfo=None):
                            matchs.append(m)
                    except Exception:
                        if m['statut'] in ["FT", "LIVE"]:
                            matchs.append(m)

            # --- FONCTION DE NORMALISATION POUR LES NULS ---
            def est_un_nul(val):
                if not val:
                    return False
                val_str = str(val).strip().lower()
                return val_str in ["draw", "match nul", "nul", "n", "x", "egalite", "égalité"]

            # --- CALCUL DU CLASSEMENT GÉNÉRAL EXACT (MATCHS + BONUS) ---
            scores_generaux = {j['id']: 0.0 for j in tous_les_joueurs}

            if tous_les_joueurs:
                # 1. Ajout des points bonus s'ils existent (Sécurisé pour points fixes ou format "Équipe:X")
                dict_points_bonus = {}
                for q in questions_bonus:
                    q_id = q.get('id')
                    brut_pts = q.get('points_bonus') if q.get('points_bonus') is not None else q.get('points', 0)
                    rep_corr = str(q.get('reponse_correcte') or '').strip().lower()
                    
                    mapping_points = {}
                    pts_fixe_defaut = 0.0
                    
                    if isinstance(brut_pts, str) and (":" in brut_pts or ";" in brut_pts):
                        parts = brut_pts.split(";")
                        for p in parts:
                            if ":" in p:
                                cle_eq, val_p = p.split(":", 1)
                                try:
                                    mapping_points[cle_eq.strip().lower()] = float(val_p.strip())
                                except ValueError:
                                    pass
                    else:
                        try:
                            pts_fixe_defaut = float(brut_pts or 0)
                        except ValueError:
                            pts_fixe_defaut = 0.0
                            
                    dict_points_bonus[q_id] = (pts_fixe_defaut, mapping_points, rep_corr)
                    
                dict_reponses_bonus = {}
                for r in reponses_bonus:
                    u_id = r.get('user_id')
                    q_id = r.get('question_id')
                    rep_j = str(r.get('reponse_joueur') or '').strip().lower()
                    dict_reponses_bonus[(u_id, q_id)] = rep_j
                    
                for j in tous_les_joueurs:
                    j_id = j['id']
                    pts_b_total = 0.0
                    for q_id, (pts_fixe_defaut, mapping_points, rep_corr) in dict_points_bonus.items():
                        rep_j = dict_reponses_bonus.get((j_id, q_id), "")
                        
                        if mapping_points:
                            rep_j_clean = str(rep_j).strip().lower()
                            for cle_map, valeur_pts in mapping_points.items():
                                if cle_map == rep_j_clean:
                                    pts_b_total += valeur_pts
                                    break
                        elif rep_corr and str(rep_j).strip().lower() == rep_corr:
                            pts_b_total += pts_fixe_defaut
                            
                    scores_generaux[j_id] += pts_b_total

                # 2. Ajout des points des matchs (FT ou LIVE avec scores)
                matchs_comptabilises = [m for m in tous_matchs_bdd if m.get('statut') in ["FT", "LIVE"]]
                if matchs_comptabilises and tous_les_pronos:
                    pronos_par_match = {}
                    for pr in tous_les_pronos:
                        m_id = pr.get('match_id')
                        if m_id:
                            if m_id not in pronos_par_match:
                                pronos_par_match[m_id] = []
                            pronos_par_match[m_id].append(pr)

                    for m in matchs_comptabilises:
                        sc_dom = m.get('score_dom')
                        sc_ext = m.get('score_ext')
                        if sc_dom is None or sc_ext is None:
                            continue
                        
                        m_id = m.get('id')
                        pronos_ce_match = pronos_par_match.get(m_id, [])
                        
                        vrai_gagnant_brut = "home" if sc_dom > sc_ext else ("away" if sc_dom < sc_ext else "draw")
                        vrai_est_nul = est_un_nul(vrai_gagnant_brut) or (sc_dom == sc_ext)
                        
                        diff = abs(sc_dom - sc_ext)
                        if diff <= 6: vraie_tranche = "1-6"
                        elif diff <= 10: vraie_tranche = "7-10"
                        elif diff <= 15: vraie_tranche = "11-15"
                        elif diff <= 20: vraie_tranche = "16-20"
                        elif diff <= 30: vraie_tranche = "21-30"
                        elif diff <= 40: vraie_tranche = "31-40"
                        elif diff <= 50: vraie_tranche = "41-50"
                        else: vraie_tranche = "51+"

                        mises_gagnant = sum(
                            1 for pr in pronos_ce_match 
                            if (vrai_est_nul and est_un_nul(pr.get('gagnant_prevu'))) or (not vrai_est_nul and pr.get('gagnant_prevu') == vrai_gagnant_brut)
                        )

                        for pr in pronos_ce_match:
                            j_id = pr.get('user_id')
                            if j_id not in scores_generaux:
                                continue
                            
                            g_prevu = pr.get('gagnant_prevu')
                            ec_prevu = pr.get('ecart_prevu')
                            p_est_nul = est_un_nul(g_prevu)
                            a_bon_vainqueur = (vrai_est_nul and p_est_nul) or (not vrai_est_nul and g_prevu == vrai_gagnant_brut)

                            if a_bon_vainqueur:
                                a_bon_ecart = True if vrai_est_nul else (ec_prevu == vraie_tranche)
                                
                                is_ose = mises_gagnant <= int(float(seuil_ose_cfg))
                                points_match_courant = float(pts_gagnant_cfg)
                                if is_ose:
                                    points_match_courant += float(pts_v_ose_cfg)
                                
                                if a_bon_ecart:
                                    points_match_courant += float(pts_ecart_cfg)
                                    if is_ose:
                                        points_match_courant += float(pts_e_ose_cfg)
                                
                                scores_generaux[j_id] += points_match_courant

            # Tri strict : score décroissant (-score), puis pseudo croissant (A-Z) en cas d'égalité
            tous_les_joueurs_tries = sorted(
                tous_les_joueurs, 
                key=lambda j: (-scores_generaux.get(j['id'], 0.0), j['pseudo'])
            )
            
            # --- SOUS-SECTION A : LES MATCHS ---
            st.subheader("🏉 Matchs Clos / En cours")
            if matchs and tous_les_joueurs_tries:
                for m in matchs:
                    label_statut = ""
                    if m.get('statut') == 'LIVE':
                        label_statut = " 🔴 LIVE"
                    elif m.get('statut') == 'NS' and (m.get('score_dom') is None or m.get('score_ext') is None):
                        label_statut = " ⏳ EN COURS"
                    
                    date_affichee = formater_date_paris(m.get('date_match'))
                    
                    sc_dom = m.get('score_dom') if m.get('score_dom') is not None else 0
                    sc_ext = m.get('score_ext') if m.get('score_ext') is not None else 0
                    
                    # Récupération des noms courts et logos
                    nom_dom_api = m.get('equipe_dom')
                    nom_ext_api = m.get('equipe_ext')
                    
                    key_dom = str(nom_dom_api).strip().lower()
                    key_ext = str(nom_ext_api).strip().lower()
                    
                    dom_court = dict_noms_courts.get(key_dom, nom_dom_api)
                    ext_court = dict_noms_courts.get(key_ext, nom_ext_api)
                    
                    dom_logo = dict_logos.get(key_dom, "")
                    ext_logo = dict_logos.get(key_ext, "")
                    
                    dom_img_html = f'<img src="{dom_logo}" width="22" height="22" style="object-fit:contain; vertical-align:middle; margin-right:4px;">' if dom_logo else ""
                    ext_img_html = f'<img src="{ext_logo}" width="22" height="22" style="object-fit:contain; vertical-align:middle; margin-left:4px;">' if ext_logo else ""
                    
                    match_banner_html = f"""
                    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 10px 14px; border-radius: 8px; border: 1px solid rgba(128, 128, 128, 0.2); margin-top: 15px;">
                        <div style="display: flex; align-items: center; gap: 4px; font-weight: bold; font-size: 14px;">
                             {dom_img_html}<span>{dom_court}</span>
                            <span style="margin: 0 8px; background-color: rgba(2, 132, 199, 0.15); color: #0284c7; padding: 2px 6px; border-radius: 6px; font-size: 13px;">{sc_dom} - {sc_ext}</span>
                            <span>{ext_court}</span>{ext_img_html}
                        </div>
                        <div style="font-size: 11px; opacity: 0.8; font-weight: 500;">
                            📅 {date_affichee} {label_statut}
                        </div>
                    </div>
                    """
                    st.markdown(match_banner_html, unsafe_allow_html=True)
                    
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
                        
                    with st.expander("🔍 Voir les pronostics des joueurs", expanded=False):
                        pronos = supabase.table("Pronostics").select("*").eq("match_id", m.get('id')).execute().data or []
                        dict_pronos = {p['user_id']: p for p in pronos} if pronos else {}
                        
                        vrai_est_nul = est_un_nul(vrai_gagnant_brut)
                        if not vrai_est_nul and sc_dom == sc_ext:
                            vrai_est_nul = True

                        pronos_ce_match = pronos if pronos else []
                        
                        mises_gagnant = sum(
                            1 for pr in pronos_ce_match 
                            if (vrai_est_nul and est_un_nul(pr.get('gagnant_prevu'))) or (not vrai_est_nul and pr.get('gagnant_prevu') == vrai_gagnant_brut)
                        )
                        
                        st.markdown("**Pronostics des joueurs (classés par ordre général) :**")
                        
                        lignes_table_html = ""
                        
                        for j in tous_les_joueurs_tries:
                            p = dict_pronos.get(j['id'])
                            est_mon_compte = (j['id'] == st.session_state.get('user_id'))
                            
                            if est_mon_compte:
                                style_ligne_joueur = "font-weight: bold; background-color: #e0f2fe; border-left: 4px solid #0284c7;"
                                pseudo_final = f"{j['pseudo']}"
                            else:
                                style_ligne_joueur = ""
                                pseudo_final = j['pseudo']
                            
                            if p:
                                g_prevu = p.get('gagnant_prevu')
                                ec_prevu = p.get('ecart_prevu')
                                
                                if est_un_nul(g_prevu):
                                    affichage_pronostic = "<b>Match Nul</b>"
                                    ligne_ecart_html = ""
                                else:
                                    if g_prevu == "home":
                                        nom_equipe_api = nom_dom_api
                                    elif g_prevu == "away":
                                        nom_equipe_api = nom_ext_api
                                    else:
                                        nom_equipe_api = str(g_prevu)
                                    
                                    clean_eq_key = str(nom_equipe_api).strip().lower()
                                    nom_court_equipe = dict_noms_courts.get(clean_eq_key, nom_equipe_api)
                                    logo_url = dict_logos.get(clean_eq_key, "")
                                    
                                    if logo_url:
                                        affichage_pronostic = f'<img src="{logo_url}" width="24" height="24" style="object-fit:contain; vertical-align:middle;" title="{nom_court_equipe}">'
                                    else:
                                        affichage_pronostic = f'<b>{nom_court_equipe}</b>'
                                    
                                    if ec_prevu is not None and str(ec_prevu).strip() != "":
                                        ligne_ecart_html = f"<br><span style='font-size:11px; color:#555555;'>{ec_prevu}</span>"
                                    else:
                                        ligne_ecart_html = ""
                                
                                pts = 0.0
                                badge_ose = ""
                                en_attente = False
                                color_bg = "#fee2e2"  
                                color_txt = "#991b1b"
                                texte_badge_resultat = "❌ Faux"
                                
                                if m.get('statut') == 'NS' and m.get('score_dom') is None:
                                    en_attente = True
                                    color_bg = "#ffedd5" 
                                    color_txt = "#9a3412"
                                    texte_badge_resultat = "⏳ En attente"
                                else:
                                    p_est_nul = est_un_nul(g_prevu)
                                    a_bon_vainqueur = (vrai_est_nul and p_est_nul) or (not vrai_est_nul and g_prevu == vrai_gagnant_brut)
                                    
                                    if a_bon_vainqueur:
                                        a_bon_ecart = True if vrai_est_nul else (ec_prevu == vraie_tranche)
                                        is_ose = mises_gagnant <= int(float(seuil_ose_cfg))
                                        
                                        pts = float(pts_gagnant_cfg)
                                        if is_ose:
                                            pts += float(pts_v_ose_cfg)
                                            
                                        if a_bon_ecart:
                                            pts += float(pts_ecart_cfg)
                                            if is_ose:
                                                pts += float(pts_e_ose_cfg)
                                            texte_badge_resultat = "⭐ Bon écart" + (" [OSÉ]" if is_ose else "")
                                            color_bg = "#d1fae5" if not is_ose else "#fde047"
                                            color_txt = "#065f46" if not is_ose else "#713f12"
                                        else:
                                            texte_badge_resultat = "✅ Bon vainqueur" + (" [OSÉ]" if is_ose else "")
                                            color_bg = "#dbeafe" if not is_ose else "#fde047"
                                            color_txt = "#1e40af" if not is_ose else "#713f12"
                                        
                                        if is_ose:
                                            badge_ose = " 🔥 OSÉ"
                                    else:
                                        pts = 0.0
                                
                                if en_attente:
                                    texte_points = "-"
                                    color_bg = "#f1f5f9"
                                    color_txt = "#64748b"
                                else:
                                    pts_affiche = int(pts) if isinstance(pts, float) and pts.is_integer() else pts
                                    texte_points = f"+{pts_affiche} pts"

                                lignes_table_html += f"""
                                <tr style="{style_ligne_joueur} border-bottom: 1px solid #f1f5f9; color: #000000;">
                                    <td style="padding: 10px; font-size: 13px; color: #000000;">{pseudo_final}</td>
                                    <td style="padding: 10px; font-size: 13px; color: #000000; vertical-align: middle;">{affichage_pronostic}{badge_ose}{ligne_ecart_html}</td>
                                    <td style="padding: 10px; text-align: center; vertical-align: middle;">
                                        <span style="color: {color_txt}; font-size: 11px; font-weight: bold;">
                                            {texte_badge_resultat}
                                        </span>
                                    </td>
                                    <td style="padding: 10px; text-align: right; vertical-align: middle;">
                                        <span style="background-color: {color_bg}; color: {color_txt}; padding: 4px 10px; border-radius: 12px; font-size: 13px; font-weight: bold; display: inline-block;">
                                            {texte_points}
                                        </span>
                                    </td>
                                </tr>
                                """
                            else:
                                lignes_table_html += f"""
                                <tr style="{style_ligne_joueur} border-bottom: 1px solid #f1f5f9; color: #000000;">
                                    <td style="padding: 10px; font-size: 13px; color: #000000;">{pseudo_final}</td>
                                    <td style="padding: 10px; font-size: 13px; font-style: italic; color: #555555; vertical-align: middle;">Aucun pronostic</td>
                                    <td style="padding: 10px; text-align: center; font-size: 11px; color: #64748b; vertical-align: middle;">❌ Absent</td>
                                    <td style="padding: 10px; text-align: right; vertical-align: middle;">
                                        <span style="background-color: #f1f5f9; color: #64748b; padding: 4px 10px; border-radius: 12px; font-size: 13px; font-weight: bold; display: inline-block;">
                                            0 pt
                                        </span>
                                    </td>
                                </tr>
                                """

                        st.markdown(f"""
                        <div style="overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff; margin-top: 5px;">
                            <table style="width: 100%; border-collapse: collapse; font-family: sans-serif; text-align: left; color: #000000;">
                                <thead style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                                    <tr>
                                        <th style="padding: 8px 10px; font-size: 12px; color: #000000;">Joueur</th>
                                        <th style="padding: 8px 10px; font-size: 12px; color: #000000;">Prono (Écart)</th>
                                        <th style="padding: 8px 10px; font-size: 12px; color: #000000; text-align: center;">Statut</th>
                                        <th style="padding: 8px 10px; font-size: 12px; color: #000000; text-align: right;">Points</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {lignes_table_html}
                                </tbody>
                            </table>
                        </div>
                        """.replace("\n", ""), unsafe_allow_html=True)
            
            # --- SOUS-SECTION B : LES QUESTIONS BONUS ---
            st.markdown("<hr style='border: 1px solid #e2e8f0; margin: 30px 0 20px 0;'>", unsafe_allow_html=True)
            st.subheader("🎯 Suivi des Questions Bonus")
            
            questions_bonus = supabase.table("Questions_Bonus").select("*").execute().data
            reponses_bonus = supabase.table("Réponses_Questions").select("*").execute().data
            
            if questions_bonus and tous_les_joueurs:
                dict_reponses = {(r['user_id'], r['question_id']): r.get('reponse_joueur') for r in reponses_bonus} if reponses_bonus else {}
                
                for q in questions_bonus:
                    st.markdown(f"##### ❓ {q['question']}")
                    
                    question_fermee = False
                    date_limite_str = q.get('date_limite')
                    if date_limite_str:
                        try:
                            if date_limite_str.endswith('Z'):
                                date_limite_str = date_limite_str[:-1] + '+00:00'
                            dt_limite_utc = datetime.fromisoformat(date_limite_str)
                            tz_paris = pytz.timezone('Europe/Paris')
                            dt_limite_q = dt_limite_utc.astimezone(tz_paris)
                            
                            if maintenant_paris.replace(tzinfo=None) >= dt_limite_q.replace(tzinfo=None):
                                question_fermee = True
                        except Exception:
                            pass
                    
                    if q.get('statut') == 'closed':
                        question_fermee = True

                    if q.get('reponse_correcte'):
                        st.markdown(f"🎯 *Réponse officielle : `{q['reponse_correcte']}`*")
                    
                    if question_fermee:
                        for j in tous_les_joueurs:
                            rep_joueur = dict_reponses.get((j['id'], q['id']))
                            
                            if rep_joueur and rep_joueur.strip() != "":
                                st.markdown(f"👤 **{j['pseudo']}** : `{rep_joueur}`")
                            else:
                                st.markdown(f"👤 **{j['pseudo']}** : <span style='color: #94a3b8; font-style: italic;'>❌ Pas de prono</span>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span style='color: #64748b; font-style: italic; font-size: 0.9em;'>🔒 Les réponses des autres joueurs seront visibles une fois la date limite dépassée.</span>", unsafe_allow_html=True)
                        
                        ma_rep = dict_reponses.get((st.session_state.user_id, q['id']))
                        if ma_rep and ma_rep.strip() != "":
                            st.markdown(f"👤 **{st.session_state.pseudo} ** : `{ma_rep}`")
                        else:
                            st.markdown(f"👤 **{st.session_state.pseudo} ** : <span style='color: #94a3b8; font-style: italic;'>❌ Tu n'as pas encore répondu</span>", unsafe_allow_html=True)
                            
                    st.markdown("---")
            else:
                st.info("Aucune question bonus enregistrée pour le moment.")
                
        except Exception as e:
            st.error(f"Erreur lors du chargement des scores : {e}")
            
# =====================================================================
# 9 - CONTENU DE L'ONGLET 4 : ADMIN (SÉCURISÉ AVEC LE TOGGLE)
# =====================================================================
elif st.session_state.onglet_actif == "⚙️" and st.session_state.is_admin:
    
    # Si le bouton est sur OFF, on bloque l'accès visuel
    if not st.session_state.mode_admin_actif:
        st.title("⚙️ Panneau d'Administration")
        st.warning("⚠️ Le mode d'édition admin est actuellement désactivé. Activez-le dans la barre latérale pour accéder aux outils d'administration.")
    else:
        st.title("⚙️ Panneau d'Administration")
        
        # --- REORGANISATION : 4 GRANDS ONGLETS PRINCIPAUX ---
        tab_matchs, tab_bonus, tab_joueurs, tab_systeme = st.tabs([
            "⚽ Gestion des Matchs",
            "🎯 Questions Bonus",
            "👥 Joueurs & Points",
            "⚙️ Système & Paramètres"
        ])
    
        # =====================================================================
        # 9.1 - ONGLET 1 : GESTION DES MATCHS (Ajout, Scores, Suppression)
        # =====================================================================
        with tab_matchs:
            sub_m1, sub_m2, sub_m3 = st.tabs(["➕ Ajouter un match", "📝 Modifier les scores", "🗑️ Supprimer un match"])
            
            # --- Sous-onglet 1.1 : Ajouter un match ---
            with sub_m1:
                st.subheader("➕ Ajouter un match manuellement")
                
                col1, col2 = st.columns(2)
                with col1:
                    equipe_dom = st.text_input("Équipe Domicile", key="dom")
                    equipe_ext = st.text_input("Équipe Extérieure", key="ext")
                with col2:
                    date_saisie = st.date_input("Date du match", key="date")
                    heure_saisie = st.time_input("Heure du match", key="heure")
                
                if st.button("Valider la création", key="btn_create_match"):
                    if equipe_dom and equipe_ext:
                        try:
                            response_last = supabase.table("Matchs").select("id").order("id", desc=True).limit(1).execute()
                            new_id = 1
                            if response_last.data:
                                new_id = int(response_last.data[0]['id']) + 1
                            
                            naive_dt = datetime.combine(date_saisie, heure_saisie)
                            paris_tz = pytz.timezone("Europe/Paris")
                            local_dt = paris_tz.localize(naive_dt)
                            utc_dt = local_dt.astimezone(pytz.UTC)
                            
                            supabase.table("Matchs").insert({
                                "id": new_id,
                                "equipe_dom": equipe_dom,
                                "equipe_ext": equipe_ext,
                                "date_match": utc_dt.isoformat(),
                                "external_id": -new_id 
                            }).execute()
                            
                            st.success(f"Match {equipe_dom} vs {equipe_ext} créé (ID: {new_id}) !")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur lors de l'ajout : {e}")
                    else:
                        st.warning("Merci de remplir les noms des équipes.")

            # --- Sous-onglet 1.2 : Matchs Existants (Scores & Statuts) ---
            with sub_m2:
                st.subheader("📝 Liste et mise à jour des scores")
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
                else:
                    st.info("Aucun match existant.")

# --- Sous-onglet 1.3 : Supprimer un match ---
            with sub_m3:
                st.subheader("🗑️ Suppression de matchs")
                st.warning("⚠️ Attention : Toute suppression de match supprime également les pronostics associés.")
                
                tous_matchs = supabase.table("Matchs").select("*").order("date_match").execute().data
                if tous_matchs:
                    match_a_supprimer = st.selectbox(
                        "Sélectionnez le match à supprimer :",
                        options=[(m['id'], f"{(m['date_match'][:10] if m.get('date_match') else 'N/A')} | {m['equipe_dom']} vs {m['equipe_ext']}") for m in tous_matchs],
                        format_func=lambda x: x[1],
                        key="select_del_match"
                    )
                    
                    if match_a_supprimer:
                        match_id = match_a_supprimer[0]
                        match_label = match_a_supprimer[1]
                        
                        confirmation = st.checkbox(f"Je confirme vouloir supprimer définitivement : {match_label}", key=f"chk_del_{match_id}")
                        
                        if st.button("Supprimer définitivement", key=f"btn_real_del_{match_id}", type="primary"):
                            if confirmation:
                                try:
                                    st.write("⏳ Tentative de suppression des pronostics liés...")
                                    res_prono = supabase.table("Pronostics").delete().eq("match_id", match_id).execute()
                                    st.write(f"Réponse pronos : {res_prono}")
                                    
                                    st.write("⏳ Tentative de suppression du match...")
                                    res_match = supabase.table("Matchs").delete().eq("id", match_id).execute()
                                    st.write(f"Réponse match : {res_match}")
                                    
                                    st.success(f"Le match '{match_label}' a été supprimé avec succès.")
                                    time.sleep(1.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erreur technique Supabase : {e}")
                            else:
                                st.warning("Veuillez cocher la case de confirmation pour valider la suppression.")
                else:
                    st.info("Aucun match trouvé en base de données.")

        # =====================================================================
        # 9.2 - ONGLET 2 : QUESTIONS BONUS (Création et Validation)
        # =====================================================================
        with tab_bonus:
            sub_q1, sub_q2 = st.tabs(["➕ Créer une question", "✅ Valider & Clôturer"])
            
            # --- Sous-onglet 2.1 : Création ---
            with sub_q1:
                st.subheader("➕ Ajouter une nouvelle Question Bonus")

                type_bareme = st.radio(
                    "Type de barème pour les points :",
                    ["Point unique pour la bonne réponse", "Points différents par réponse"],
                    key="admin_type_bareme_94",
                    horizontal=True
                )

                points_stockes = ""

                if type_bareme == "Point unique pour la bonne réponse":
                    pts_uniques = st.number_input("Nombre de points à gagner :", min_value=1, value=5, step=1, key="admin_pts_uniques_94")
                    points_stockes = str(pts_uniques)
                else:
                    st.info("👉 Entrez les réponses possibles et les points associés sous la forme : `Réponse:Points`. Séparez les blocs par des points-virgules ( ; ).")
                    ex_bareme = st.text_input(
                        "Configuration du barème (Exemple: Toulouse:5 ; La Rochelle:3) :",
                        placeholder="Option1:5 ; Option2:2",
                        key="admin_bareme_multiple_94"
                    )
                    points_stockes = ex_bareme.strip()

                txt_question = st.text_input("Intitulé de la question bonus :", key="admin_txt_question_94")

                st.markdown("📅 **Date et Heure limite pour répondre :**")
                col_date_q, col_heure_q = st.columns(2)
                with col_date_q:
                    date_limite_q = st.date_input("Date limite :", value=datetime.now().date(), key="date_limite_q_bonus")
                with col_heure_q:
                    heure_limite_q = st.time_input("Heure limite :", value=datetime.now().time(), key="heure_limite_q_bonus")

                if st.button("Créer la question bonus", key="admin_btn_creer_94", use_container_width=True):
                    if txt_question and points_stockes:
                        try:
                            dt_limite_combinee = datetime.combine(date_limite_q, heure_limite_q)
                            tz_paris = pytz.timezone('Europe/Paris')
                            dt_limite_paris = tz_paris.localize(dt_limite_combinee)
                            iso_date_limite = dt_limite_paris.astimezone(pytz.utc).isoformat()

                            supabase.table("Questions_Bonus").insert({
                                "question": txt_question,
                                "points": points_stockes,
                                "statut": "open",
                                "date_limite": iso_date_limite
                            }).execute()
                            st.success("🎉 Question bonus créée avec succès !")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur lors de la création dans Supabase : {e}")
                    else:
                        st.warning("⚠️ Veuillez remplir l'intitulé de la question et la configuration des points.")

            # --- Sous-onglet 2.2 : Validation / Clôture ---
            with sub_q2:
                st.subheader("🎯 Valider et Clôturer une Question Bonus")
                
                try:
                    questions_ouvertes = supabase.table("Questions_Bonus").select("*").eq("statut", "open").execute().data
                    
                    if questions_ouvertes:
                        for q_a_valider in questions_ouvertes:
                            st.write(f"❓ **Question :** {q_a_valider['question']}")
                            
                            pts_config = str(q_a_valider.get("points") or q_a_valider.get("points_bonus") or "").strip()
                            options_possibles = []
                            
                            if ":" in pts_config:
                                segments = pts_config.split(";")
                                for s in segments:
                                    if ":" in s:
                                        option_nom, _ = s.split(":")
                                        options_possibles.append(option_nom.strip())
                            
                            if options_possibles:
                                choix_admin = st.selectbox(
                                    "Sélectionnez la réponse correcte :",
                                    ["-- Choisir le vainqueur --"] + options_possibles,
                                    key=f"val_sel_95_{q_a_valider['id']}"
                                )
                                
                                bouton_desactive = (choix_admin == "-- Choisir le vainqueur --")
                                
                                if st.button("Valider ce résultat", key=f"btn_val_sel_95_{q_a_valider['id']}", disabled=bouton_desactive):
                                    try:
                                        supabase.table("Questions_Bonus").update({
                                            "reponse_correcte": choix_admin.strip().lower(),
                                            "statut": "closed"
                                        }).eq("id", q_a_valider['id']).execute()
                                        
                                        st.success(f"🎉 Question clôturée ! Réponse '{choix_admin}' enregistrée.")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Erreur lors de la validation : {e}")
                            else:
                                st.warning("⚠️ Barème à point unique détecté. Saisie manuelle obligatoire :")
                                choix_manuel = st.text_input("Réponse correcte :", key=f"val_txt_95_{q_a_valider['id']}")
                                
                                if st.button("Clôturer (Saisie manuelle)", key=f"btn_val_txt_95_{q_a_valider['id']}"):
                                    if choix_manuel.strip():
                                        try:
                                            supabase.table("Questions_Bonus").update({
                                                "reponse_correcte": choix_manuel.strip().lower(),
                                                "statut": "closed"
                                            }).eq("id", q_a_valider['id']).execute()
                                            st.success("🎉 Question clôturée avec succès !")
                                            time.sleep(1)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Erreur : {e}")
                            
                            st.markdown("---")
                    else:
                        st.info("Aucune question bonus en attente de validation.")
                        
                except Exception as e:
                    st.error(f"Erreur lors du chargement du module de validation : {e}")

# =====================================================================
        # 9.3 - ONGLET 3 : JOUEURS & POINTS (Score classement + Points manuels)
        # =====================================================================
        with tab_joueurs:
            st.subheader("👥 Gestion des Joueurs & Points")
            st.info("Retrouvez la liste des joueurs, leur score au classement, leurs points manuels et les actions associées.")
            
            tous_les_joueurs = supabase.table("Joueurs").select("*").execute().data
            
            if tous_les_joueurs:
                for j in tous_les_joueurs:
                    with st.container(border=True):
                        # Récupération des scores (on gère le cas où la colonne points_manuels n'existe pas encore)
                        score_classement = j.get('score', 0) or 0
                        points_manuels = j.get('points_manuels', 0) or 0
                        
                        # Affichage des infos sous forme de colonnes pour les métriques
                        col_info1, col_m1, col_m2 = st.columns([2, 1, 1])
                        with col_info1:
                            st.markdown(f"### 👤 {j.get('pseudo', 'Inconnu')}")
                        with col_m1:
                            st.metric(label="Score Classement", value=f"{score_classement} pts")
                        with col_m2:
                            st.metric(label="Points Manuels", value=f"{points_manuels:+d}" if points_manuels != 0 else "0")
                        
                        # Ligne des boutons d'action
                        b_col1, b_col2, b_col3 = st.columns(3)
                        
                        # 1. Bouton Points (modifie uniquement les points manuels)
                        with b_col1:
                            with st.popover("🎁 Points", use_container_width=True):
                                st.write(f"**Ajuster les points manuels de {j['pseudo']}**")
                                pts_delta = st.number_input("Points à ajouter (+) ou retirer (-)", value=1, step=1, key=f"pts_val_{j['id']}")
                                
                                if st.button("Appliquer", key=f"btn_apply_pts_{j['id']}", use_container_width=True):
                                    try:
                                        nouveau_pts_manuels = points_manuels + int(pts_delta)
                                        # On met à jour uniquement la colonne dédiée aux points manuels
                                        supabase.table("Joueurs").update({"points_manuels": nouveau_pts_manuels}).eq("id", j['id']).execute()
                                        st.success(f"✅ {pts_delta:+d} pts manuels appliqués !")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Erreur : {e}")

                        # 2. Bouton Mot de passe
                        with b_col2:
                            with st.popover("🔑 MDP", use_container_width=True):
                                st.write(f"**Nouveau MDP pour {j['pseudo']}**")
                                new_pwd = st.text_input("Mot de passe", type="password", key=f"pwd_{j['id']}")
                                
                                if st.button("Valider", key=f"btn_reinit_pwd_{j['id']}", use_container_width=True):
                                    if new_pwd:
                                        try:
                                            admin_client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"])
                                            admin_client.auth.admin.update_user_by_id(j['id'], {"password": new_pwd})
                                            st.success("Mis à jour !")
                                            time.sleep(1)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Erreur : {e}")
                                    else:
                                        st.warning("Saisir un MDP.")

                        # 3. Bouton Suppression
                        with b_col3:
                            with st.popover("🗑️ Suppr", use_container_width=True):
                                st.error(f"Supprimer **{j['pseudo']}** ?")
                                
                                if st.button("Oui, supprimer", key=f"btn_final_del_{j['id']}", type="primary", use_container_width=True):
                                    try:
                                        supabase.table("Pronostics").delete().eq("user_id", j['id']).execute()
                                        supabase.table("Réponses_Questions").delete().eq("user_id", j['id']).execute()
                                        supabase.table("Joueurs").delete().eq("id", j['id']).execute()
                                        st.success(f"Joueur supprimé.")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Erreur : {e}")
            else:
                st.info("Aucun joueur trouvé.")
        # =====================================================================
        # 9.4 - ONGLET 4 : SYSTÈME & PARAMÈTRES (Barème, API, Zone de danger)
        # =====================================================================
        with tab_systeme:
            sub_s1, sub_s2, sub_s3 = st.tabs(["📊 Barème des points", "🔌 Tour de contrôle API", "🚨 Zone de Danger"])
            
            # --- Sous-onglet 4.1 : Barème & Points ---
            with sub_s1:
                st.subheader("📊 Configuration du Barème de Points")
                st.info("Ajuste les coefficients ci-dessous. Ils seront appliqués lors du calcul des résultats.")
                
                if "pts_vainqueur" not in st.session_state: st.session_state.pts_vainqueur = 2
                if "pts_ecart" not in st.session_state: st.session_state.pts_ecart = 2
                if "pct_ose" not in st.session_state: st.session_state.pct_ose = 3
                if "pts_v_ose" not in st.session_state: st.session_state.pts_v_ose = 2
                if "pts_e_ose" not in st.session_state: st.session_state.pts_e_ose = 3
                
                with st.form("form_bareme_points"):
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        pts_v = st.number_input("Points Vainqueur trouvé", min_value=0, value=int(st.session_state.pts_vainqueur), step=1)
                        pts_e = st.number_input("Points Écart parfait (Bonus)", min_value=0, value=int(st.session_state.pts_ecart), step=1)
                    with col_b2:
                        seuil_o = st.number_input(
                            "Nombre max de gagnants pour prono osé (X)", 
                            min_value=1, 
                            value=int(st.session_state.pct_ose), 
                            step=1, 
                            help="Le bonus s'active uniquement si le nombre de joueurs ayant trouvé le bon vainqueur est INFÉRIEUR OU ÉGAL à ce nombre X."
                        )
                        pts_v_o = st.number_input("Points vainqueur osé (M)", min_value=0, value=int(st.session_state.pts_v_ose), step=1, help="Points supplémentaires ajoutés si le vainqueur osé est trouvé.")
                        pts_e_o = st.number_input("Points Ecart osé (N)", min_value=0, value=int(st.session_state.pts_e_ose), step=1, help="Points supplémentaires ajoutés pour l'écart sur un prono osé (total M+N si vainqueur + écart).")
                    
                    if st.form_submit_button("💾 Sauvegarder le barème"):
                        data_bareme = {
                            "id": "default_config",
                            "pts_gagnant": int(pts_v),
                            "pts_ecart": int(pts_e),
                            "seuil_poursentage_ose": int(seuil_o),
                            "pts_vainqueur_ose": int(pts_v_o),
                            "pts_ecart_ose": int(pts_e_o)
                        }
                        
                        try:
                            supabase.table("Configuration").upsert(data_bareme, on_conflict="id").execute()
                            
                            st.session_state.pts_vainqueur = pts_v
                            st.session_state.pts_ecart = pts_e
                            st.session_state.pct_ose = seuil_o
                            st.session_state.pts_v_ose = pts_v_o
                            st.session_state.pts_e_ose = pts_e_o
                            
                            st.success(f"🎉 Barème sauvegardé ! Le seuil est fixé à moins de {seuil_o} joueur(s) gagnant(s) (Bonus : +{pts_v_o} pts pour le vainqueur, +{pts_v_o}+{pts_e_o} pts pour vainqueur+écart).")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur : {e}")

# --- Sous-onglet 4.2 : Tour de contrôle API ---
            with sub_s2:
                st.subheader("🔌 Gestion de l'API")
                
                # 1. Affichage du compteur en direct depuis Supabase
                try:
                    response_api = supabase.table("Configuration").select("*").eq("id", "default_config").execute()
                    if response_api.data:
                        config_api = response_api.data[0]
                        current_count = config_api.get("api_request_count", 0)
                        current_logs = config_api.get("api_request_logs", []) or []
                    else:
                        current_count = 0
                        current_logs = []
                except Exception as e:
                    current_count = 0
                    current_logs = []
                
                st.metric(label="Requêtes envoyées à l'API", value=f"{current_count}/50")
            
                col_api1, col_api2 = st.columns(2)
            
                # Récupération de ta clé Supabase depuis tes secrets Streamlit existants
                supabase_key = st.secrets["SUPABASE_KEY"]
            
                with col_api1:
                    if st.button("MAJ score (Live)"):
                        with st.spinner("Exécution de la mise à jour live..."):
                            try:
                                url = "https://puznnphyulbrnxjojnnc.supabase.co/functions/v1/clever-responder"
                                headers = {"Authorization": f"Bearer {supabase_key}"}
                                
                                response = requests.post(url, headers=headers)
                                
                                if response.status_code == 200:
                                    st.success("Mise à jour des scores effectuée avec succès !")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"Erreur (Code {response.status_code}) : {response.text}")
                            except Exception as e:
                                st.error(f"Erreur lors de l'appel : {e}")
            
                with col_api2:
                    if st.button("MAJ Calendrier"):
                        with st.spinner("Exécution de la mise à jour du calendrier..."):
                            try:
                                url = "https://puznnphyulbrnxjojnnc.supabase.co/functions/v1/dynamic-endpoint"
                                headers = {"Authorization": f"Bearer {supabase_key}"}
                                
                                response = requests.post(url, headers=headers)
                                
                                if response.status_code == 200:
                                    st.success("Mise à jour du calendrier effectuée avec succès !")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"Erreur (Code {response.status_code}) : {response.text}")
                            except Exception as e:
                                st.error(f"Erreur lors de l'appel : {e}")
            
                with st.expander("📜 Historique des 20 dernières requêtes"):
                    if current_logs:
                        for log in current_logs:
                            st.text(log)
                    else:
                        st.info("Aucune requête enregistrée pour le moment.")

            # --- Sous-onglet 4.3 : Zone de danger ---
            with sub_s3:
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
                            supabase.table("Joueurs").update({"points_manuels": 0}).not_.is_("id", "null").execute()
                            st.success("🎉 Reset saison terminé !")
                            st.balloons()
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: 
                            st.error(f"Erreur : {e}")
