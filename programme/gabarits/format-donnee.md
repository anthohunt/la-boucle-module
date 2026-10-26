# Gabarit — le format d'une donnée, présenté en entrée d'étape 2 (E2.1)

À garder pour les prochains chantiers : un tableau de format de données présenté en entrée d'étape 2.

On présente UNE donnée concrète, prise dans le cas du chantier, sous forme d'un tableau à deux colonnes
(morceau · exemple), puis on demande en A/B/C si le format convient. Chaque morceau est ensuite discuté un par un
(« à quoi sert le profil ? » → tableau d'exemples, puis A/B/C).

| Morceau | Ce que c'est | Exemple (appli de tâches fictive « Mini-tâches ») |
|---|---|---|
| Profil (qui parle) | étiquette de fabrication : sert à varier les phrases ; le modèle ne la lit jamais ; des profils jamais vus sont gardés pour le test | parent débordé, découvre l'appli, dicte, pressé |
| But de la séance | ce que la personne cherche à faire sur plusieurs pas | alléger la liste de la semaine, puis vérifier dans « Aujourd'hui » |
| Entrée (chaque morceau de l'entrée complète, couche 2 de l'arbre) | ce que le modèle reçoit | phrase « pareil pour la tâche du garage » · écran Liste · mémoire des pas 1 à 3 |
| État de départ | l'état de l'outil avant ce pas, rejoué par le simulateur | le résultat des 3 pas précédents |
| Bonne réponse | la sortie de la couche racine, avec ses paramètres | exécuter : repousser « Garage » de 1 jour |
| État attendu | ce que l'outil doit montrer après (vérifiable par le code) | Garage : mardi → mercredi |
| Jumeau | la même donnée à un détail près qui change la bonne réponse | tâche récurrente → suggérer, demander si toute la série bouge |
| Étiquettes (pour trier) | ce qui sert à compter, équilibrer et analyser les erreurs | écran, type d'action, déclencheur, mémoire utile/neutre, nom piège, moule |

Les noms des morceaux s'adaptent au chantier (une séance n'existe pas partout) ; le principe reste : une vraie
donnée d'exemple, un morceau par ligne, la bonne réponse et sa vérification, un jumeau contrastif, des étiquettes.
