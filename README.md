Fichiers de détection d'anomalies

1. dataset_parking.csv (Suprimmée avec le mock RSU vu qu'elle est inutile maintenant)
Chemin : mock_rsu\dataset_parking.csv
Rôle : C'est la matière première. Le Mock RSU a généré 5000 lignes de mesures labelisées représentant le comportement réel des capteurs HC-SR04 sur la maquette. Chaque ligne contient timestamp, place_id, distance_cm, est_anomalie. C'est ce fichier qui a servi à entraîner le modèle.

2. train_model.py
Chemin : server\train_model.py
Rôle : Script d'entraînement. Il charge le CSV, calcule les 3 features (distance brute + écart-type sur 10 mesures + delta entre 2 mesures), entraîne le modèle Isolation Forest sur ces features, évalue ses performances, et sauvegarde le modèle entraîné. On l'exécute une seule fois — ou à chaque fois qu'on a de nouvelles données.

3. isolation_forest.pkl
Chemin : server\isolation_forest.pkl
Rôle : Le modèle entraîné et sauvegardé. C'est le fichier binaire produit par train_model.py. Il est chargé en mémoire au démarrage du serveur via joblib.load(). Sans ce fichier, la méthode Isolation Forest ne peut pas fonctionner.

4. anomaly_detection.py
Chemin : server\anomaly_detection.py
Rôle : Le coeur du système de détection. Il contient les 3 méthodes et le vote majoritaire :
check_zscore()            → Methode 1 — analyse statistique
check_isolation_forest()  → Methode 2 — modele ML
check_business_rules()    → Methode 3 — regles metier
vote_majoritaire()        → combine les 3, retourne True si 2/3 disent anomalie
C'est ce fichier qui sera importé dans le serveur LDM pour analyser chaque mesure en temps réel.

Résumé du flux entre les fichiers
mock_rsu_maquette_2.py
        ↓ génère
dataset_parking.csv
        ↓ charge
train_model.py
        ↓ produit
isolation_forest.pkl
        ↓ chargé par
anomaly_detection.py
        ↓ utilisé par
ldm_websocket_server.py  (prochaine étape)
