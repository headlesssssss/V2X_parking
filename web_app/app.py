from flask import Flask, render_template, jsonify
import json
import os
import heapq

app = Flask(__name__)

# --- CONFIGURATION DES CHEMINS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On remonte d'un dossier (..) pour entrer dans 'server'
SERVER_DIR = os.path.join(BASE_DIR, '..', 'server') 
CONF_PATH = os.path.join(SERVER_DIR, 'conf_parking.json')
ETAT_PATH = os.path.join(SERVER_DIR, 'etat_parking.json')

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# --- ALGORITHME A* ---
def a_star(grid, start, goal):
    rows, cols = len(grid), len(grid[0])
    open_set = []
    heapq.heappush(open_set, (0, start))  # File de priorité : (coût f, position)
    came_from = {}                         # Dictionnaire de reconstruction du chemin
    g_score = {start: 0}                  # Coût réel depuis le point de départ
    f_score = {start: abs(start[0]-goal[0]) + abs(start[1]-goal[1])}  # f = g + h (Manhattan)

    while open_set:
        current = heapq.heappop(open_set)[1]  # Nœud avec le plus petit coût f

        if current == goal:
            path = []
            while current in came_from:       # Reconstruction du chemin en remontant
                path.append({"row": current[0], "col": current[1]})
                current = came_from[current]
            path.append({"row": start[0], "col": start[1]})
            return path[::-1]                 # Retour du chemin dans le bon sens

        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:  # 4 directions possibles
            neighbor = (current[0] + dr, current[1] + dc)
            
            if 0 <= neighbor[0] < rows and 0 <= neighbor[1] < cols:
                # Une case est franchissable si c'est de la route (0),
                # l'entrée (98) ou la place de destination (goal)
                is_walkable = (grid[neighbor[0]][neighbor[1]] == 0 or
                               grid[neighbor[0]][neighbor[1]] == 98 or
                               neighbor == goal)
                
                if is_walkable:
                    tentative_g_score = g_score[current] + 1
                    if tentative_g_score < g_score.get(neighbor, float('inf')):
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        # Mise à jour de f = g + heuristique Manhattan
                        f_score[neighbor] = tentative_g_score + abs(neighbor[0]-goal[0]) + abs(neighbor[1]-goal[1])
                        heapq.heappush(open_set, (f_score[neighbor], neighbor))
    return []  # Aucun chemin trouvé

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_parking_data():
    try:
        conf = load_json(CONF_PATH)
        etat_complet = load_json(ETAT_PATH)
        
        grid = conf.get('grid', [])
        # On récupère le dictionnaire des places soit dans .places, soit à la racine
        etat_places = etat_complet.get("places", etat_complet)
        
        if not grid:
            return jsonify({"error": "Grille non trouvée dans conf_parking.json"}), 500

        # 1. Localisation dynamique de l'entrée (98) et des places (10-90)
        entry_coords = None
        spots_coords = {}
        
        for r in range(len(grid)):
            for c in range(len(grid[r])):
                val = grid[r][c]
                if val == 98:
                    entry_coords = (r, c)
                elif 10 <= val <= 90 and val != 99:
                    spots_coords[str(val)] = (r, c)

        # Sécurité si 98 n'est pas dans la grille
        if not entry_coords:
            meta = conf.get('metadata', {}).get('entry_point', {"row": 0, "col": 0})
            entry_coords = (meta['row'], meta['col'])

        # 2. Recherche de la meilleure place libre
        free_spots = [s for s, status in etat_places.items() if status == "FREE"]
        best_path = []
        best_spot = None
        
        if free_spots and entry_coords:
            shortest_len = float('inf')
            for spot_id in free_spots:
                if spot_id in spots_coords:
                    goal = spots_coords[spot_id]
                    path = a_star(grid, entry_coords, goal)
                    
                    if path and len(path) < shortest_len:
                        shortest_len = len(path)
                        best_path = path
                        best_spot = spot_id
        
        return jsonify({
            "grid": grid,
            "status": etat_places,
            "best_spot": best_spot,
            "path": best_path,
            "metadata": conf.get('metadata', {})
        })

    except Exception as e:
        print(f"❌ Erreur Serveur : {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Lance le serveur sur le port 5000
    app.run(debug=True, port=5000)