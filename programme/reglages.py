"""Réglages du module La boucle v2 : un fichier JSON facultatif, des variables d'environnement, des valeurs neutres.

Ordre de lecture (le premier fichier trouvé gagne) :
  1. $LA_BOUCLE_REGLAGES (chemin d'un fichier JSON) ;
  2. ./boucle-module.json à la racine du dépôt du module ;
  3. ~/.config/la-boucle-module/boucle-module.json.
Un fichier n'a besoin de contenir que les clés qu'il change ; le modèle complet est boucle-module.example.json.
Aucun secret ne se range ici : la commande de notification reçoit ses secrets de son propre environnement.
"""
import json
import os

ICI = os.path.dirname(os.path.abspath(__file__))

DEFAUTS = {
    # Où vivent les chantiers (un dossier par chantier). $LA_BOUCLE_V2_RACINE ou --racine l'emportent.
    'racine_chantiers': '~/.la-boucle/chantiers',
    # Le canal des confirmations de scellement : un dossier que seul le compte `uid` écrit (0 = root).
    'confirmations': {'dossier': '/var/lib/la-boucle-module/confirmations', 'uid': 0},
    # Relevé des comptes Claude (quotas, sessions) : une URL http(s), un chemin de fichier JSON, ou '' (aucun relevé :
    # les comptes de la liste ci-dessous sont connus sans quota). Format : docs/reglages.md.
    'releve_comptes': '',
    # Les comptes Claude que le chantier peut brancher à ses agents (noms neutres ; ajoute les tiens).
    'comptes': [{'id': 'compte-a', 'nom': 'Compte A'}, {'id': 'compte-b', 'nom': 'Compte B'}],
    # Le lanceur d'agents : la commande (liste) qui démarre un agent ; l'agent reçoit LA_BOUCLE_CHANTIER=<chantier>.
    # Vide : l'opérateur lance ses agents lui-même. Le dossier des fins reçoit <nom>.fin (« code heure ») à la fin d'un agent.
    'agents': {'lanceur': [], 'dossier_fins': '~/.la-boucle/fins'},
    # Notification (agent fini ou en panne quand l'opérateur est absent). Désactivée par défaut. La commande (liste)
    # reçoit le message en dernier argument. Jamais de jeton dans ce fichier : mets-le dans l'environnement de la commande.
    'notification': {'active': False, 'commande': []},
    # La commande du moteur de La boucle (dépôt la-boucle-engine), donnée aux agents des étapes 3 et 4.
    'moteur': ['python3', '-m', 'boucle'],
    # Bibliothèque entre chantiers (facultative) ; $LA_BOUCLE_BIBLIOTHEQUE l'emporte.
    'bibliotheque': '',
}


def _fusion(base, haut):
    out = dict(base)
    for k, v in (haut or {}).items():
        out[k] = _fusion(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def chemin_reglages():
    for c in (os.environ.get('LA_BOUCLE_REGLAGES'), os.path.join(ICI, '..', 'boucle-module.json'),
              os.path.expanduser('~/.config/la-boucle-module/boucle-module.json')):
        if c and os.path.isfile(c):
            return c
    return None


def charger():
    """Les réglages effectifs : défauts, puis fichier, avec les ~ développés dans les chemins."""
    r = dict(DEFAUTS)
    c = chemin_reglages()
    if c:
        with open(c, encoding='utf-8') as f:
            r = _fusion(DEFAUTS, json.load(f))
    r['racine_chantiers'] = os.path.expanduser(r['racine_chantiers'])
    r['confirmations'] = dict(r['confirmations'], dossier=os.path.expanduser(r['confirmations']['dossier']))
    r['agents'] = dict(r['agents'], dossier_fins=os.path.expanduser(r['agents']['dossier_fins']))
    if r.get('bibliotheque'):
        r['bibliotheque'] = os.path.expanduser(r['bibliotheque'])
    return r
