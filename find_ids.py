import requests

RAPIDAPI_KEY = "TA_CLE_API"
headers = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "rugbyapi2.p.rapidapi.com"
}

# 1. On liste les catégories (ex: France, International, etc.)
url_categories = "https://rugbyapi2.p.rapidapi.com/api/rugby/getRugbyTournamentCategories"

response = requests.get(url_categories, headers=headers)
print("--- CATÉGORIES ---")
print(response.json())

# 2. Une fois que tu as une catégorie (ex: id=12), tu peux lister les tournois de cette catégorie
# Remplace '12' par l'id de la catégorie que tu veux
params = {"category_id": "12"} 
url_tournaments = "https://rugbyapi2.p.rapidapi.com/api/rugby/getTournamentsByCategory"

response = requests.get(url_tournaments, headers=headers, params=params)
print("\n--- TOURNOIS DE LA CATÉGORIE ---")
print(response.json())
