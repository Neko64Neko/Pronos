import streamlit as st
from supabase import create_client
from datetime import datetime
import requests
import time
import threading

# 1. CONNEXION À SUPABASE
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# =====================================================================
# SYSTEME AUTOMATIQUE DE RECUPERATION DES MATCHS (FUSION INTELLIGENTE)
# =====================================================================

def verifier_et_importer_matchs():
    """Appelle l'API Rugby et fusionne intelligemment avec les matchs manuels pour éviter les doublons."""
    url_api = "https://v1.rugby.api-sports.io/games"
    headers = {
        'x-rapidapi-key': st.secrets["API_RUGBY_KEY"],
        'x-rapidapi-host': 'v1.rugby.api-sports.io'
    }
    
    saisons_a_tester = [2024, 2025]
    matchs_trouves_au_total = 0

    for saison in saisons_a_tester:
        params = {"league": 16, "season": saison}
        try:
            response = requests.get(url_api, headers=headers, params=params)
            data = response.json()
            
            if data.get("response"):
                for game in data["response"]:
                    api_id = game["id"]
                    eq_dom = game["teams"]["home"]["name"]
                    eq_ext = game["teams"]["away"]["name"]
                    
                    # 🔍 ÉTAPE DE SÉCURITÉ : Est-ce qu'on a déjà créé ce match à la main ?
                    # On cherche un match en base avec les mêmes équipes
                    match_existant = supabase.table("Matchs").select("id").eq("equipe_dom", eq_dom).eq("equipe_ext", eq_ext).execute().data
                    
                    if match_existant:
                        ancien_id = match_existant[0]["id"]
                        
                        # Si l'ID en base est différent de l'API (donc c'est notre match manuel)
                        if ancien_id != api_id:
                            try:
                                # 1. On met d'abord à jour les pronos des joueurs vers le nouvel ID officiel de l'API
                                supabase.table("Pronostics").update({"match_id": api_id}).eq("match_id", ancien_id).execute()
                                # 2. On supprime l'ancien match manuel devenu inutile
                                supabase.table("Matchs").delete().eq("id", ancien_id).execute()
                            except Exception as e_migration:
                                print(f"Erreur lors de la fusion/migration d'ID : {e_migration}")
                    
                    # Maintenant on peut insérer/mettre à jour les données fraîches de l'API (scores, statuts en direct)
                    match_data = {
                        "id": api_id,
                        "equipe_dom": eq_dom,
                        "equipe_ext": eq_ext,
                        "date_match": game["date"], 
                        "score_dom": game["scores"]["home"],
                        "score_ext": game["scores"]["away"],
                        "statut": game["status"]["short"]
                    }
                    
                    try:
                        supabase.table("Matchs").upsert(match_data).execute()
                        matchs_trouves_au_total += 1
                    except Exception as e_db:
                        print(f"Erreur d'insertion Supabase : {e_db}")
                    
        except Exception as e:
            print(f"Erreur lors de l'appel API pour la saison {saison} : {e}")
            
    return matchs_trouves_au_total

def Planning_Background_Loop():
    """Boucle de surveillance horaire qui tourne en arrière-plan."""
    dernier_import_journalier = None
    
    while True:
        maintenant = datetime.now()
        
        # 1. Vérification si un match est actuellement en direct
        try:
            matchs_en_cours = supabase.table("Matchs").select("id").in_("statut", ["1H", "2H", "HT", "LIVE"]).execute()
            a_un_match_en_cours = len(matchs_en_cours.data) > 0
        except Exception:
            a_un_match_en_cours = False

        # REGLE A : Un match est en cours -> Fréquence de 5 minutes pour actualiser les scores
        if a_un_match_en_cours:
            verifier_et_importer_matchs()
            time.sleep(300)
            continue

        # REGLE B : Aucun match en cours -> Appel unique quotidien à 9h00 du matin
        if maintenant.hour == 9 and maintenant.minute == 0:
            if dernier_import_journalier != maintenant.date():
                verifier_et_importer_matchs()
                dernier_import_journalier = maintenant.date()
        
        # Attente de 30 secondes avant la prochaine vérification
        time.sleep(30)

# Démarrage du robot automatique
if "background_thread" not in st.session_state:
    st.session_state.background_thread = threading.Thread(target=Planning_Background_Loop, daemon=True)
    st.session_state.background_thread.start()

# =====================================================================
# INITIALISATION DES VARIABLES DE SESSION
# =====================================================================
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "pseudo" not in st.session_state:
    st.session_state.pseudo = ""

# LISTE DES ÉCARTS CONFIGURÉS
TRANCHES_ECARTS = ["1-6", "7-10", "11-15", "16-20", "21-30", "31-40", "41-50", "51+"]

# ---- ÉCRAN DE CONNEXION / INSCRIPTION ----
if st.session_state.user_id is None:
    st.title("🏉 Pronos Top 14")
    onglet = st.tabs(["Se connecter", "S'inscrire"])
    
    with onglet[0]: # CONNEXION
        mail = st.text_input("Email", key="login_email")
        mdp = st.text_input("Mot de passe", type="password", key="login_pass")
        if st.button("Connexion"):
            try:
                res = supabase.auth.sign_in_with_password({"email": mail, "password": mdp})
                profil = supabase.table("Joueurs").select("*").eq("id", res.user.id).single().execute()
                st.session_state.user_id = res.user.id
                st.session_state.is_admin = profil.data["is_admin"]
                st.session_state.pseudo = profil.data["pseudo"]
                st.success(f"Ravi de vous revoir {st.session_state.pseudo} !")
                st.rerun()
            except Exception:
                st.error("Erreur : Identifiants incorrects.")

    with onglet[1]: # INSCRIPTION
        new_mail = st.text_input("Email", key="reg_email")
        new_mdp = st.text_input("Mot de passe (6 caractères min)", type="password", key="reg_pass")
        pseudo = st.text_input("Ton Pseudo pour le classement")
        
        if st.button("Créer mon compte"):
            if len(pseudo) < 3:
                st.error("Pseudo trop court !")
            else:
                try:
                    res = supabase.auth.sign_up({"email": new_mail, "password": new_mdp})
                    supabase.table("Joueurs").insert({
                        "id": res.user.id,
                        "pseudo": pseudo,
                        "email": new_mail,
                        "score": 0,
                        "is_admin": False
                    }).execute()
                    st.success("Compte créé avec succès ! Connecte-toi maintenant.")
                except Exception as e:
                    st.error(f"Erreur technique : {e}")

# ---- APPLICATION CONNECTÉE ----
else:
    # Barre latérale de navigation
    st.sidebar.title(f"🏉 {st.session_state.pseudo}")
    if st.sidebar.button("Déconnexion"):
        st.session_state.user_id = None
        st.rerun()
        
    page = st.sidebar.radio("Menu", ["Classement", "Faire mes Pronostics", "Résultats & Direct"])

    # VISIBILITÉ STRICTE ADMIN : Zone de contrôle & Ajout manuel de secours
    if st.session_state.is_admin:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🛠️ Zone Admin")
        
        if st.sidebar.button("🔄 Synchroniser l'API Top 14"):
            with st.sidebar.spinner("Vérification de l'API..."):
                nb_matchs = verifier_et_importer_matchs()
                st.sidebar.success(f"🎉 Succès ! {nb_matchs} match(s) synchronisés de l'API.")
                st.rerun()

        st.sidebar.markdown("---")
        st.sidebar.subheader("➕ Ajouter un Match Manuellement")
        with st.sidebar.form("form_ajout_match"):
            eq_dom = st.text_input("Équipe Domicile", placeholder="Ex: Toulouse")
            eq_ext = st.text_input("Équipe Extérieur", placeholder="Ex: Bordeaux")
            date_choisie = st.date_input("Date du match")
            heure_choisie = st.time_input("Heure du match")
            
            submit_match = st.form_submit_button("➕ Créer le match de force")
            
            if submit_match:
                if eq_dom and eq_ext:
                    datetime_combine = datetime.combine(date_choisie, heure_choisie).isoformat()
                    import random
                    id_manuel = int(datetime.timestamp(datetime.combine(date_choisie, heure_choisie))) + random.randint(1, 1000)
                    
                    data_match_manuel = {
                        "id": id_manuel,
                        "equipe_dom": eq_dom,
                        "equipe_ext": eq_ext,
                        "date_match": datetime_combine,
                        "score_dom": None,
                        "score_ext": None,
                        "statut": "NS"
                    }
                    try:
                        supabase.table("Matchs").insert(data_match_manuel).execute()
                        st.sidebar.success(f"🎉 Match {eq_dom} vs {eq_ext} ajouté !")
                        st.rerun()
                    except Exception as e_add:
                        st.sidebar.error(f"Erreur d'insertion : {e_add}")
                else:
                    st.sidebar.error("Veuillez remplir les noms d'équipes.")

    # --- PAGE 1 : CLASSEMENT ---
    if page == "Classement":
        st.title("🏆 Classement Général")
        try:
            joueurs = supabase.table("Joueurs").select("pseudo, score").order("score", desc=True).execute()
            if joueurs.data:
                st.table(joueurs.data)
            else:
                st.info("Aucun joueur pour le moment.")
        except Exception as e_page:
            st.error(f"Erreur d'affichage classement : {e_page}")

    # --- PAGE 2 : SÉLECTION DES PRONOSTICS ---
    elif page == "Faire mes Pronostics":
        st.title("✍️ Saisir les Pronostics")
        now = datetime.utcnow().isoformat()
        
        id_joueur_concerne = st.session_state.user_id
        if st.session_state.is_admin:
            st.warning("🛠️ Mode Admin actif")
            try:
                liste_j = supabase.table("Joueurs").select("id, pseudo").execute().data
                if liste_j:
                    choix_j = st.selectbox("Pronostiquer au nom de :", options=liste_j, format_func=lambda x: x["pseudo"])
                    if choix_j:
                        id_joueur_concerne = choix_j["id"]
            except Exception:
                pass

        try:
            matchs = supabase.table("Matchs").select("*").gt("date_match", now).order("date_match").execute().data
            
            if matchs:
                for m in matchs:
                    st.subheader(f"🏟️ {m['equipe_dom']} vs {m['equipe_ext']}")
                    st.caption(f"Date limite : {m['date_match']}")
                    
                    vrai_nom_gagnant = st.radio(
                        f"Qui va gagner ? ({m['equipe_dom']} vs {m['equipe_ext']})",
                        options=[m['equipe_dom'], m['equipe_ext'], "Match Nul"],
                        key=f"winner_{m['id']}"
                    )
                    ecart = st.selectbox("Écart de score :", options=TRANCHES_ECARTS, key=f"margin_{m['id']}")
                    
                    if st.button("Enregistrer le prono", key=f"btn_{m['id']}"):
                        val_gagnant = "home" if vrai_nom_gagnant == m['equipe_dom'] else ("away" if vrai_nom_gagnant == m['equipe_ext'] else "draw")
                        existant = supabase.table("Pronostics").select("id").eq("user_id", id_joueur_concerne).eq("match_id", m['id']).execute().data
                        
                        donnees_prono = {
                            "user_id": id_joueur_concerne,
                            "match_id": m['id'],
                            "gagnant_prevu": val_gagnant,
                            "ecart_prevu": ecart
                        }
                        
                        if existant:
                            supabase.table("Pronostics").update(donnees_prono).eq("id", existant[0]["id"]).execute()
                        else:
                            supabase.table("Pronostics").insert(donnees_prono).execute()
                            
                        st.success("Prono enregistré !")
            else:
                st.info("Aucun match disponible aux pronostics pour le moment.")
                
                tous_les_matchs = supabase.table("Matchs").select("id").execute().data
                if tous_les_matchs:
                    st.caption(f"💡 (Info Admin : Il y a {len(tous_les_matchs)} match(s) en base Supabase, mais leur date est passée. Ils s'affichent dans l'onglet 'Résultats & Direct').")
                    
        except Exception as e_match:
            st.error(f"Erreur lors de la récupération des matchs depuis Supabase : {e_match}")

    # --- PAGE 3 : RÉSULTATS & DIRECT ---
    elif page == "Résultats & Direct":
        st.title("📊 Résultats & Matchs en cours")
        now = datetime.utcnow().isoformat()
        
        try:
            matchs_lances = supabase.table("Matchs").select("*").lte("date_match", now).order("date_match", desc=True).execute().data
            
            if matchs_lances:
                for m in matchs_lances:
                    st.write(f"### {m['equipe_dom']} {m['score_dom'] if m['score_dom'] is not None else 0} - {m['score_ext'] if m['score_ext'] is not None else 0} {m['equipe_ext']}")
                    st.caption(f"Statut : {m['statut']}")
                    
                    with st.expander("Voir les pronostics des joueurs sur ce match"):
                        pronos = supabase.table("Pronostics").select("gagnant_prevu, ecart_prevu, Joueurs(pseudo)").eq("match_id", m['id']).execute().data
                        if pronos:
                            for p in pronos:
                                nom_equipe_choisie = m['equipe_dom'] if p['gagnant_prevu'] == 'home' else (m['equipe_ext'] if p['gagnant_prevu'] == 'away' else "Match Nul")
                                st.write(f"👤 **{p['Joueurs']['pseudo']}** : {nom_equipe_choisie} (Écart : {p['ecart_prevu']})")
                        else:
                            st.write("Aucun prono enregistré pour ce match.")
                    st.markdown("---")
            else:
                st.info("Les matchs s'afficheront ici dès qu'ils auront débuté.")
        except Exception as e_lance:
            st.error(f"Erreur d'affichage des résultats : {e_lance}")