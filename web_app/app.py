import json
import os
import heapq
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# --- CONFIGURATION DES CHEMINS ---
# On remonte d'un dossier (..) pour aller chercher les JSON dans ton dossier 'server'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(BASE_DIR, '..', 'server')
CONF_PATH = os.path.join(SERVER_DIR, 'conf_parking.json')
ETAT_PATH = os.path.join(SERVER_DIR, 'etat_parking.json')

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

# --- ALGORITHME A* (Recherche de chemin) ---
def heuristic(a, b):
    # Distance de Manhattan
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def a_star(grid, start, goal):
    rows = len(grid)
    cols = len(grid[0])
    
    frontier = []
    heapq.heappush(frontier, (0, start))
    came_from = {start: None}
    cost_so_far = {start: 0}

    while frontier:
        current = heapq.heappop(frontier)[1]

        if current == goal:
            break

        # Vérifier les 4 directions (Haut, Bas, Gauche, Droite)
        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            next_node = (current[0] + dx, current[1] + dy)
            r, c = next_node

            # Si on est dans les limites de la grille
            if 0 <= r < rows and 0 <= c < cols:
                val = grid[r][c]
                # On ne peut marcher QUE sur la route (0), l'entrée (98), ou la place visée
                if val == 0 or val == 98 or next_node == goal:
                    new_cost = cost_so_far[current] + 1
                    if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                        cost_so_far[next_node] = new_cost
                        priority = new_cost + heuristic(goal, next_node)
                        heapq.heappush(frontier, (priority, next_node))
                        came_from[next_node] = current

    # Reconstruire le chemin
    path = []
    if goal in came_from:
        curr = goal
        while curr != start:
            path.append({"row": curr[0], "col": curr[1]})
            curr = came_from[curr]
        path.append({"row": start[0], "col": start[1]})
        path.reverse()
    
    return path

# --- ROUTES DE L'API WEB ---

@app.route('/')
def index():
    # Sert la page HTML principale
    return render_template('index.html')

@app.route('/api/data')
def get_parking_data():
    try:
        conf = load_json(CONF_PATH)
        etat = load_json(ETAT_PATH)
        grid = conf['grid']
        
        # 1. Trouver les coordonnées de l'entrée et des places
        entry_coords = (conf['metadata']['entry_point']['row'], conf['metadata']['entry_point']['col'])
        spots_coords = {}
        
        for r in range(len(grid)):
            for c in range(len(grid[r])):
                val = grid[r][c]
                if 10 <= val <= 90 and val != 98 and val != 99:
                    spots_coords[str(val)] = (r, c)

        # 2. Trouver la place libre la plus proche
        free_spots = [spot for spot, status in etat.items() if status == "FREE"]
        best_path = []
        best_spot = None
        
        if free_spots:
            shortest_distance = float('inf')
            
            for spot in free_spots:
                if spot in spots_coords:
                    goal = spots_coords[spot]
                    path = a_star(grid, entry_coords, goal)
                    
                    if path and len(path) < shortest_distance:
                        shortest_distance = len(path)
                        best_path = path
                        best_spot = spot
                        
        return jsonify({
            "grid": grid,
            "status": etat,
            "best_spot": best_spot,
            "path": best_path
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Lance le serveur Web sur le port 5000
    app.run(debug=True, host='0.0.0.0', port=5000)