#!/usr/bin/env python3
"""Confirmation d'un scellement par l'utilisateur — à lancer par le compte de confiance (root par défaut).

Ce script écrit la confirmation dans le dossier réservé (réglage confirmations.dossier) ; le programme ne l'accepte
que si le fichier appartient au compte de confiance (réglage confirmations.uid, root par défaut). Tout autre canal
(application, bouton) peut écrire le même fichier, à condition d'avoir les mêmes droits.
Il montre d'abord le récapitulatif de la demande et ne confirme que l'empreinte exacte qu'on lui donne.

    sudo -E python3 confirmer.py <chantier> <etape> <empreinte>        # empreinte : celle de la demande (ou ses 12 premiers caractères)
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reglages  # noqa: E402

REGLAGES = reglages.charger()
RACINE = os.environ.get('LA_BOUCLE_V2_RACINE') or REGLAGES['racine_chantiers']
CONFIRMATIONS = REGLAGES['confirmations']['dossier']
UID_CONFIRMATION = REGLAGES['confirmations']['uid']


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    if os.geteuid() != UID_CONFIRMATION:
        print('Refusé : seul le compte de confiance confirme (le canal que les agents ne peuvent pas écrire).')
        return 1
    chantier, etape, emp = sys.argv[1], int(sys.argv[2]), sys.argv[3].strip().lower()
    chemin = os.path.join(RACINE, chantier, f'etape{etape}', 'demande-scellement.json')
    with open(chemin, encoding='utf-8') as f:
        demande = json.load(f)
    if len(emp) < 12 or not demande['empreinte'].startswith(emp):
        print(f"Refusé : l'empreinte donnée ne correspond pas à la demande ({demande['empreinte'][:12]}…).")
        return 1
    print(f"Étape {etape} du chantier {chantier} — {len(demande['documents'])} documents, empreinte {demande['empreinte'][:12]}…")
    for d in demande['decisions'][-20:]:
        print(f"  {d['sous_etape']}{' ' + d['point'] if d.get('point') else ''} : « {d['citation']} »")
    os.makedirs(CONFIRMATIONS, mode=0o755, exist_ok=True)
    cible = os.path.join(CONFIRMATIONS, f'{chantier}-etape{etape}.json')
    with open(cible + '.tmp', 'w', encoding='utf-8') as f:
        json.dump({'empreinte': demande['empreinte'], 'a': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'par': 'operateur', 'canal': 'secours-root'}, f, ensure_ascii=False)
    os.chmod(cible + '.tmp', 0o644)
    os.replace(cible + '.tmp', cible)
    print(f'Confirmation posée : {cible}. Le programme scelle l’étape à son prochain relevé.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
