#!/usr/bin/env python3
"""Programme du module La boucle v2 : l'état d'un chantier, tenu dans ses fichiers.

Le mod Claude Code n'est que l'interface : chaque geste (ouvrir, décider, avancer, écrire une sortie, rouvrir,
noter un événement) passe par ce programme, qui valide, écrit et journalise. Tout ce qui peut être cadré l'est ici,
jamais par l'agent (« tout ce qui peut être cadré l'est par le programme »).

Usage : boucle.py <commande> [--racine DIR]   (paramètres en JSON sur l'entrée standard, réponse JSON sur la sortie)
Racine des chantiers : --racine, sinon $LA_BOUCLE_V2_RACINE, sinon le réglage racine_chantiers (reglages.py).

Fichiers d'un chantier (<racine>/<chantier>/) :
  chantier.json      états des sous-étapes et des étapes, catégorie
  decisions.jsonl    chaque décision de l'utilisateur, mot pour mot et datée 
  registre.json      règles du chantier (seuils « propose » puis « scelle »)
  journal.jsonl      tout ce qui se passe, horodaté, lisible par un programme 
  etapeN/...         les sorties des sous-étapes ; .versions/ garde chaque version remplacée
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
if ICI not in sys.path:
    sys.path.insert(0, ICI)
import reglages  # noqa: E402

REGLAGES = reglages.charger()
RACINE_DEFAUT = REGLAGES['racine_chantiers']
# Le canal des confirmations : un dossier que seul le compte UID_CONFIRMATION écrit (root par défaut). Une
# confirmation n'y vaut que si le fichier appartient à ce compte et n'est inscriptible par personne d'autre ; l'écrire
# est le geste de l'utilisateur (confirmer.py, ou le canal de son choix qui écrit le même fichier).
CONFIRMATIONS = REGLAGES['confirmations']['dossier']
UID_CONFIRMATION = REGLAGES['confirmations']['uid']
NOM = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
ETATS = ('a_faire', 'en_cours', 'a_valider', 'validee', 'scellee')
# Réponse « autre chose » (frictions) : option D ou texte libre hors des options proposées.
OPTIONS = ('A', 'B', 'C', 'D', 'autre')


class Refus(Exception):
    """Un geste que le programme refuse : la raison revient telle quelle à l'agent."""


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def charger_json(chemin, defaut=None):
    try:
        with open(chemin, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return defaut


def ecrire_atomique(chemin, texte):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(chemin), prefix='.tmp-')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(texte)
    os.replace(tmp, chemin)


def ecrire_json(chemin, valeur):
    ecrire_atomique(chemin, json.dumps(valeur, ensure_ascii=False, indent=2) + '\n')


def ajouter_ligne(chemin, valeur):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'a', encoding='utf-8') as f:
        f.write(json.dumps(valeur, ensure_ascii=False) + '\n')


def lire_lignes(chemin):
    try:
        with open(chemin, encoding='utf-8') as f:
            return [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []


def empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(65536), b''):
            h.update(bloc)
    return h.hexdigest()


# ─── Parcours ────────────────────────────────────────────────────────────────────────────────────────────────────


def parcours():
    return charger_json(os.path.join(ICI, 'parcours.json'))


def categories():
    return charger_json(os.path.join(ICI, 'categories.json'))['categories']


def toutes_sous_etapes(p=None):
    p = p or parcours()
    return [dict(s, etape=e['n']) for e in p['etapes'] for s in e['sous_etapes']]


def visibles(c, p=None):
    """Les sous-étapes du chantier : celles du parcours, plus celles qu'apporte sa catégorie (E1.3)."""
    cat = (c.get('categorie') or {}).get('id')
    ajoutees = set()
    for k in categories():
        if k['id'] == cat:
            ajoutees = set(k['ajoute'])
    # Une sous-étape propre à une voie (« voies » dans le parcours, ex. E2.2.1 la stratégie de génération) n'apparaît
    # que si la voie choisie en E2.2 en fait partie ; tant que la voie n'est pas choisie, elle reste affichée.
    voie = c.get('voie_donnees')
    return [s for s in toutes_sous_etapes(p) if (not s.get('categorie') or s['id'] in ajoutees)
            and (not voie or not s.get('voies') or voie in s['voies'])]


def actives(c, p=None):
    """Les sous-étapes qui font avancer le chantier : les visibles, moins celles marquées « future » dans le parcours.
    Une sous-étape future reste décrite et affichée, mais ne s'ouvre pas, ne se valide
    pas et ne bloque ni la recette ni le scellement de son étape."""
    return [s for s in visibles(c, p) if not s.get('future')]


def sous_etape(c, sid):
    for s in visibles(c):
        if s['id'] == sid:
            return s
    connues = {s['id'] for s in toutes_sous_etapes()}
    if sid in connues:
        raise Refus(f"La sous-étape {sid} n'est pas dans le parcours de ce chantier (elle dépend d'une autre catégorie).")
    raise Refus(f'Sous-étape inconnue : {sid}.')


# ─── Chantier ────────────────────────────────────────────────────────────────────────────────────────────────────


class Chantier:
    def __init__(self, racine, nom):
        if not NOM.match(nom or ''):
            raise Refus('Nom de chantier invalide : minuscules, chiffres et tirets, 40 caractères au plus.')
        self.nom = nom
        self.dossier = os.path.join(racine, nom)

    def chemin(self, *morceaux):
        return os.path.join(self.dossier, *morceaux)

    def existe(self):
        return os.path.exists(self.chemin('chantier.json'))

    @contextlib.contextmanager
    def verrou(self):
        os.makedirs(self.dossier, exist_ok=True)
        with open(self.chemin('.verrou'), 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def lire(self):
        c = charger_json(self.chemin('chantier.json'))
        if c is None:
            raise Refus(f"Le chantier « {self.nom} » n'existe pas : ouvre-le par /la-boucle {self.nom}.")
        c['_dossier'] = self.dossier
        return c

    def enregistrer(self, c):
        ecrire_json(self.chemin('chantier.json'), {k: v for k, v in c.items() if k != '_dossier'})

    def journaliser(self, type_, **donnees):
        ev = {'a': maintenant(), 'type': type_, **donnees}
        ajouter_ligne(self.chemin('journal.jsonl'), ev)
        return ev

    def chemin_sortie(self, relatif):
        """Un chemin d'écriture sûr, sous le dossier du chantier, hors des fichiers du programme."""
        rel = os.path.normpath(str(relatif or '').strip().lstrip('/'))
        if rel in ('', '.') or rel.startswith('..') or os.path.isabs(rel):
            raise Refus(f'Chemin refusé : {relatif} (il doit rester dans le dossier du chantier).')
        if not re.match(r'^etape[1-5]/', rel):
            raise Refus(f'Chemin refusé : {relatif} (les sorties vont sous etape1/ à etape5/).')
        if '/.versions/' in '/' + rel + '/' or os.path.basename(rel).startswith('.'):
            raise Refus(f'Chemin refusé : {relatif}.')
        return rel


def nouveau(nom):
    p = parcours()
    etats = {}
    for s in toutes_sous_etapes(p):
        etats[s['id']] = {'etat': 'a_faire'}
    t = maintenant()
    etats['E1.1'] = {'etat': 'en_cours', 'depuis': t}
    return {
        'nom': nom,
        'ouvert_le': t,
        'categorie': None,
        'sous_etapes': etats,
        'etapes': {str(e['n']): {'etat': 'ouverte' if e['n'] == 1 else 'fermee'} for e in p['etapes']},
        'sessions': [],
    }


def etat_de(c, sid):
    return (c['sous_etapes'].get(sid) or {}).get('etat', 'a_faire')


def etape_courante(c):
    for n in sorted(c['etapes'], key=int):
        if c['etapes'][n]['etat'] != 'scellee':
            return int(n)
    return None


def suivante(c, sid):
    """La sous-étape qui suit `sid` dans la même étape (on ne change d'étape qu'au scellement)."""
    vis = actives(c)
    ids = [s['id'] for s in vis]
    i = ids.index(sid)
    for s in vis[i + 1:]:
        if s['etape'] == vis[i]['etape'] and etat_de(c, s['id']) in ('a_faire',):
            return s['id']
    return None


def ch_dossier(c):
    return c.get('_dossier')


def ce_qui_attend(c):
    """Ce qui attend l'utilisateur, en tête du volet : une validation, une décision, ou la sous-étape en cours."""
    n = etape_courante(c)
    if n is None:
        return None
    sol = [x for x in lire_lignes(os.path.join(ch_dossier(c), 'etape4', 'sollicitations.jsonl')) if x.get('statut') != 'traitee'] if ch_dossier(c) else []
    if sol:
        return {'sous_etape': 'E4.3', 'etape': 4, 'quoi': f"La boucle te sollicite : {sol[0].get('quoi', 'voir le volet')}", 'toi': True}
    if c['etapes'][str(n)]['etat'] == 'a_sceller':
        return {'sous_etape': None, 'etape': n, 'quoi': f"Confirmer le scellement de l'étape {n} sur ton téléphone"}
    vis = [s for s in actives(c) if s['etape'] == n]
    for s in vis:
        if etat_de(c, s['id']) == 'a_valider':
            return {'sous_etape': s['id'], 'etape': n, 'quoi': f"Valider : {s['titre']}"}
    for s in vis:
        if etat_de(c, s['id']) == 'en_cours':
            quoi = s['titre'] if s['qui'] == 'moi' else f"{s['titre']} (un agent travaille)"
            return {'sous_etape': s['id'], 'etape': n, 'quoi': quoi, 'toi': s['qui'] == 'moi'}
    if all(etat_de(c, s['id']) == 'validee' for s in vis):
        return {'sous_etape': None, 'etape': n, 'quoi': f"Sceller l'étape {n}"}
    return None


def progression_points(c, s, decisions):
    pts = s.get('points') or []
    if not pts:
        return None
    tranches = {}
    for d in decisions:
        if d.get('sous_etape') == s['id'] and d.get('point'):
            tranches[d['point']] = d
    return {'tranches': sum(1 for p in pts if p['id'] in tranches and tranches[p['id']].get('statut') != 'rouvert'), 'total': len(pts)}


def vue(ch, c):
    """L'état complet, tel que le volet le dessine et que l'agent le lit."""
    p = parcours()
    decisions = lire_lignes(ch.chemin('decisions.jsonl'))
    registre = charger_json(ch.chemin('registre.json'), {})
    vis = visibles(c, p)
    par_se = {}
    for d in decisions:
        par_se.setdefault(d['sous_etape'], []).append(d)
    etapes = []
    for e in p['etapes']:
        ses = []
        for s in [s for s in vis if s['etape'] == e['n']]:
            st = c['sous_etapes'].get(s['id'], {})
            sorties = []
            for rel in s.get('sortie', []):
                if rel in ('registre', 'journal'):
                    continue
                chemin = ch.chemin(rel)
                sorties.append({'chemin': rel, 'absolu': chemin, 'existe': os.path.exists(chemin)})
            ses.append({
                'id': s['id'], 'titre': s['titre'], 'qui': s['qui'], 'etat': st.get('etat', 'a_faire'),
                'depuis': st.get('depuis'), 'valide_le': st.get('valide_le'), 'citation': st.get('citation'),
                'entree': s.get('entree'), 'consigne': s.get('consigne'), 'sorties': sorties,
                'decisions': [{k: d.get(k) for k in ('a', 'point', 'resume', 'citation', 'option', 'statut')} for d in par_se.get(s['id'], [])],
                'points': progression_points(c, s, decisions),
                'notion': bool(s.get('notion')),
                'future': bool(s.get('future')),
            })
        etapes.append({'n': e['n'], 'titre': e['titre'], 'resume': e['resume'], 'tu_decides': e['tu_decides'],
                       'etat': c['etapes'][str(e['n'])]['etat'], 'scelle': c['etapes'][str(e['n'])].get('scelle'),
                       'demande': demande_en_attente(ch, c, e['n']),
                       'sous_etapes': ses})
    return {
        'chantier': c['nom'], 'dossier': ch.dossier, 'ouvert_le': c['ouvert_le'], 'categorie': c.get('categorie'),
        'etape_courante': etape_courante(c), 'attend': ce_qui_attend(c), 'etapes': etapes,
        'registre': registre, 'reprise': reprise(ch, c, decisions), 'regles': p['regles_communes'],
        'points': {s['id']: s['points'] for s in vis if s.get('points')},
        'arbre': vue_arbre(ch), 'catalogue': vue_catalogue(ch), 'besoin': extrait(ch.chemin('etape1', 'besoin.md'), 1500),
        'relecture': [x for x in (resume_accord(ch, 1), resume_accord(ch, 2)) if x],
        'mesures': mesures(ch, c),
        'lexique': lexique(ch),
        'calcul': charger_json(ch.chemin('etape2', 'calcul', 'resultat.json')),
        'fabrication': vue_fabrication(ch),
        'relecture_banc': relecture_etat(ch) if os.path.exists(ch.chemin('etape3', 'a-relire.jsonl')) else None,
        'confirmation_portes': confirmation_portes(ch),
        'boucle': vue_boucle(ch),
        'usage': vue_usage(ch),
        'livre': c['etapes']['5']['etat'] == 'scellee',
        'reglages': {'moteur': ' '.join(REGLAGES['moteur']), 'lanceur_agents': ' '.join(REGLAGES['agents']['lanceur'])},
    }


def demande_en_attente(ch, c, n):
    if c['etapes'][str(n)]['etat'] != 'a_sceller':
        return None
    d = charger_json(ch.chemin(f'etape{n}', 'demande-scellement.json')) or {}
    return {'a': d.get('a'), 'empreinte': d.get('empreinte'), 'documents': len(d.get('documents', []))}


def extrait(chemin, n):
    try:
        with open(chemin, encoding='utf-8', errors='replace') as f:
            return f.read(n)
    except FileNotFoundError:
        return None


def resume_accord(ch, passe):
    r = charger_json(ch.chemin('etape1', 'relecture', f'passe-{passe}', 'accord.json'))
    if not r:
        return None
    return {k: r[k] for k in ('passe', 'relecteurs', 'exemples', 'par_critere')} | {'desaccords': len(r['desaccords'])}


def reprise(ch, c, decisions):
    """De quoi reprendre sans rien relire : dernière décision, ce qui s'est passé depuis la dernière session."""
    journal = lire_lignes(ch.chemin('journal.jsonl'))
    sessions = c.get('sessions') or []
    depuis = sessions[-2]['a'] if len(sessions) >= 2 else None
    pendant = [ev for ev in journal if depuis and ev['a'] > depuis and ev['type'] in ('agent_fini', 'agent_panne', 'programme_fini', 'programme_panne', 'scellement_confirme')]
    derniere = decisions[-1] if decisions else None
    return {
        'derniere_decision': derniere,
        'pendant_absence': pendant[-10:],
        'derniere_session': depuis,
        'evenements': len(journal),
    }


# ─── Commandes ───────────────────────────────────────────────────────────────────────────────────────────────────


def cmd_ouvrir(ch, a):
    with ch.verrou():
        neuf = not ch.existe()
        c = nouveau(ch.nom) if neuf else ch.lire()
        c.setdefault('sessions', []).append({'a': maintenant(), 'session': a.get('session'), 'role': a.get('role', 'utilisateur')})
        c['sessions'] = c['sessions'][-50:]
        ch.enregistrer(c)
        ch.journaliser('chantier_cree' if neuf else 'chantier_repris', session=a.get('session'), role=a.get('role', 'utilisateur'))
        if neuf:
            ch.journaliser('sous_etape', sous_etape='E1.1', etat='en_cours')
        return dict(vue(ch, c), neuf=neuf)


def cmd_etat(ch, a):
    with ch.verrou():
        c = ch.lire()
        appliquer_confirmations(ch, c)
    return vue(ch, c)


def cmd_avancer(ch, a):
    sid, etat = a.get('sous_etape'), a.get('etat')
    if etat not in ('en_cours', 'a_valider', 'validee'):
        raise Refus("État refusé : en_cours, a_valider ou validee (le scellement passe par l'outil sceller).")
    with ch.verrou():
        c = ch.lire()
        s = sous_etape(c, sid)
        n = s['etape']
        if s.get('future'):
            raise Refus(f"{sid} est une sous-étape future : décrite pour plus tard, elle ne s'ouvre ni ne se valide maintenant, et ne bloque rien.")
        if c['etapes'][str(n)]['etat'] == 'scellee':
            raise Refus(f"L'étape {n} est scellée : la rouvrir demande une confirmation explicite (outil rouvrir).")
        if c['etapes'][str(n)]['etat'] == 'fermee':
            raise Refus(f"L'étape {n} n'est pas encore ouverte : l'étape {n - 1} doit d'abord être scellée.")
        if sid == derniere_sous_etape(c, n)['id']:
            raise Refus(f"{sid} se valide par le scellement de l'étape (outil sceller), confirmé sur le téléphone.")
        avant = etat_de(c, sid)
        citation = str(a.get('citation') or '').strip()
        if etat == 'validee' and not citation:
            raise Refus("Validation refusée : il faut la réponse de l'utilisateur, mot pour mot (citation).")
        if etat == 'validee' and avant == 'validee':
            raise Refus(f'{sid} est déjà validée.')
        if etat == 'validee' and s.get('points_avant_validation'):
            # E4.1 : le plafond du test des deux façons (G1) et les sorties prudentes (G8)
            # sont posés à l'utilisateur et tranchés avant le départ.
            tranches = {d.get('point') for d in lire_lignes(ch.chemin('decisions.jsonl')) if d.get('sous_etape') == sid and d.get('statut') != 'rouvert'}
            manquants = [x['id'] + ' (' + x['titre'] + ')' for x in s.get('points') or [] if x['id'] not in tranches]
            if manquants:
                raise Refus(f"{sid} ne se valide pas : points pas encore tranchés par l'utilisateur : {', '.join(manquants)}.")
        if etat == 'validee':
            absents = [r for r in s.get('requis_avant_validation') or [] if not os.path.exists(ch.chemin(r))]
            if absents:
                raise Refus(f"{sid} ne se valide pas sans : {', '.join(absents)}.")
        t = maintenant()
        st = {'etat': etat, 'depuis': t}
        if etat == 'validee':
            st.update(valide_le=t, citation=citation, debut=(c['sous_etapes'].get(sid) or {}).get('debut') or (c['sous_etapes'].get(sid) or {}).get('depuis'))
        else:
            st['debut'] = (c['sous_etapes'].get(sid) or {}).get('debut') or t
        c['sous_etapes'][sid] = st
        ch.journaliser('sous_etape', sous_etape=sid, etat=etat, avant=avant, citation=citation or None)
        if etat == 'validee' and s.get('notion'):
            # Le lexique des notions comprises (étape 2) : l'utilisateur a validé sa compréhension, mot pour mot.
            ajouter_ligne(ch.chemin('etape2', 'lexique.jsonl'), {'a': t, 'sous_etape': sid, 'notion': s['titre'], 'citation': citation})
        ouverte = None
        if etat == 'validee':
            ouverte = suivante(c, sid)
            if ouverte:
                c['sous_etapes'][ouverte] = {'etat': 'en_cours', 'depuis': t, 'debut': t}
                ch.journaliser('sous_etape', sous_etape=ouverte, etat='en_cours', avant='a_faire')
        ch.enregistrer(c)
        return {'sous_etape': sid, 'etat': etat, 'ouverte': ouverte, 'attend': ce_qui_attend(c)}


def cmd_decision(ch, a):
    sid = a.get('sous_etape')
    citation = str(a.get('citation') or '').strip()
    resume = str(a.get('resume') or '').strip()
    if not citation:
        raise Refus("Décision refusée : il faut les mots exacts de l'utilisateur (citation).")
    if not resume:
        raise Refus('Décision refusée : résume la décision en une ligne.')
    option = a.get('option')
    if option is not None and option not in OPTIONS:
        raise Refus(f'Option inconnue : {option} (A, B, C, D ou autre).')
    with ch.verrou():
        c = ch.lire()
        s = sous_etape(c, sid)
        if c['etapes'][str(s['etape'])]['etat'] == 'scellee':
            raise Refus(f"L'étape {s['etape']} est scellée : aucune décision ne s'y ajoute sans la rouvrir.")
        point = a.get('point')
        if point is not None:
            ids = [p['id'] for p in s.get('points') or []]
            if point not in ids:
                raise Refus(f"Point inconnu pour {sid} : {point}." + (f" Points : {', '.join(ids)}." if ids else ' Cette sous-étape n\'a pas de points.'))
        d = {'a': maintenant(), 'sous_etape': sid, 'point': point, 'resume': resume, 'citation': citation, 'option': option,
             'statut': 'rouvert' if a.get('rouvert') else 'tranche'}
        ajouter_ligne(ch.chemin('decisions.jsonl'), d)
        ch.journaliser('decision', sous_etape=sid, point=point, option=option, citation=citation)
        if etat_de(c, sid) == 'a_faire':
            c['sous_etapes'][sid] = {'etat': 'en_cours', 'depuis': d['a'], 'debut': d['a']}
            ch.enregistrer(c)
        if s.get('points'):
            ecrire_cadrage(ch, s)
        decisions = lire_lignes(ch.chemin('decisions.jsonl'))
        return {'decision': d, 'points': progression_points(c, s, decisions)}


def ecrire_cadrage(ch, s):
    """La sortie d'une sous-étape à points (E1.4 → etape1/cadrage.json), régénérée à chaque décision."""
    derniers = {}
    for d in lire_lignes(ch.chemin('decisions.jsonl')):
        if d['sous_etape'] == s['id'] and d.get('point'):
            derniers[d['point']] = d
    points = []
    for p in s['points']:
        d = derniers.get(p['id'])
        points.append({'id': p['id'], 'titre': p['titre'], 'decision': d['resume'] if d else None,
                       'citation': d['citation'] if d else None, 'date': d['a'] if d else None,
                       'etat': (d['statut'] if d else 'ouvert')})
    rel = [r for r in s['sortie'] if r.endswith('.json')][0]
    ecrire_json(ch.chemin(rel), {'sous_etape': s['id'], 'points': points})


def cmd_categorie(ch, a):
    cat, citation = a.get('categorie'), str(a.get('citation') or '').strip()
    connues = {k['id']: k for k in categories()}
    if cat not in connues and cat != 'aucune':
        raise Refus(f"Catégorie inconnue : {cat}. Connues : {', '.join(connues)}, ou « aucune ».")
    if not citation:
        raise Refus("Il faut la réponse de l'utilisateur, mot pour mot (citation).")
    with ch.verrou():
        c = ch.lire()
        if c['etapes']['1']['etat'] == 'scellee':
            raise Refus("L'étape 1 est scellée : la catégorie ne change plus sans la rouvrir.")
        avant = set(s['id'] for s in visibles(c))
        c['categorie'] = {'id': 'classique' if cat == 'aucune' else cat, 'raison': a.get('raison'), 'citation': citation,
                          'a': maintenant(), 'aucune_ne_convenait': cat == 'aucune'}
        apres = [s['id'] for s in visibles(c)]
        ajoutees = [s for s in apres if s not in avant]
        if cat == 'aucune':
            ajouter_ligne(ch.chemin('etape1/cas-futures-categories.jsonl'), {'a': maintenant(), 'raison': a.get('raison'), 'citation': citation})
        ch.enregistrer(c)
        ch.journaliser('categorie', categorie=c['categorie']['id'], ajoutees=ajoutees, citation=citation)
        return {'categorie': c['categorie'], 'ajoutees': ajoutees}


def fichiers_scelles(ch, c):
    out = set()
    for n, e in c['etapes'].items():
        if e['etat'] == 'scellee':
            for f in (e.get('scelle') or {}).get('documents', []):
                out.add(f['chemin'])
    return out


def cmd_ecrire(ch, a):
    rel = ch.chemin_sortie(a.get('chemin'))
    if usage_protege(rel):
        raise Refus(f'{rel} est tenu par le programme (boucle d’usage, G7) : passe par les outils usage_*.')
    contenu = a.get('contenu')
    if not isinstance(contenu, str):
        raise Refus('Contenu manquant (texte).')
    with ch.verrou():
        c = ch.lire()
        n = int(rel[5])
        if c['etapes'][str(n)]['etat'] == 'scellee' or rel in fichiers_scelles(ch, c):
            raise Refus(f"{rel} est scellé : le rouvrir demande une confirmation explicite.")
        cible = ch.chemin(rel)
        version = None
        if os.path.exists(cible):
            with open(cible, encoding='utf-8', errors='replace') as f:
                ancien = f.read()
            if ancien == contenu:
                return {'chemin': rel, 'absolu': cible, 'inchange': True}
            version = os.path.join('.versions', rel + '.' + maintenant().replace(':', ''))
            ecrire_atomique(ch.chemin(version), ancien)
        ecrire_atomique(cible, contenu)
        h = empreinte(cible)
        ch.journaliser('sortie_ecrite', chemin=rel, empreinte=h, version_precedente=version, pourquoi=a.get('pourquoi'))
        return {'chemin': rel, 'absolu': cible, 'empreinte': h, 'version_precedente': version}


def cmd_lire(ch, a):
    rel = os.path.normpath(str(a.get('chemin') or '').lstrip('/'))
    if rel.startswith('..'):
        raise Refus('Chemin refusé.')
    if usage_protege(rel):
        raise Refus(f'{rel} est tenu par le programme (boucle d’usage, G7) : la part scellée et ses étiquettes ne se lisent jamais ; la sonde lit etape5/usage/sonde.jsonl par ses outils.')
    cible = ch.chemin(rel)
    if not os.path.isfile(cible):
        raise Refus(f"{rel} n'existe pas encore.")
    with open(cible, encoding='utf-8', errors='replace') as f:
        return {'chemin': rel, 'absolu': cible, 'contenu': f.read(200_000)}


def cmd_rouvrir(ch, a):
    sid = a.get('sous_etape')
    raison = str(a.get('raison') or '').strip()
    if not raison:
        raise Refus('Dis pourquoi la sous-étape est rouverte (raison).')
    with ch.verrou():
        c = ch.lire()
        s = sous_etape(c, sid)
        if c['etapes'][str(s['etape'])]['etat'] == 'scellee':
            raise Refus(f"L'étape {s['etape']} est scellée : la rouvrir demande une confirmation explicite sur le téléphone (lot scellement).")
        avant = etat_de(c, sid)
        t = maintenant()
        c['sous_etapes'][sid] = {'etat': 'en_cours', 'depuis': t, 'debut': t, 'rouverte': (c['sous_etapes'].get(sid) or {}).get('rouverte', 0) + 1}
        # La sous-étape qui venait de s'ouvrir derrière, sans aucune décision, se referme : une seule « en cours »
        # (bienvenue rouverte, besoin resté en cours).
        decidees = {d.get('sous_etape') for d in lire_lignes(ch.chemin('decisions.jsonl'))}
        vis = visibles(c)
        ids = [x['id'] for x in vis]
        for x in vis[ids.index(sid) + 1:]:
            if x['etape'] == s['etape'] and etat_de(c, x['id']) == 'en_cours' and x['id'] not in decidees:
                c['sous_etapes'].pop(x['id'], None)
        ch.enregistrer(c)
        ch.journaliser('sous_etape_rouverte', sous_etape=sid, avant=avant, raison=raison, par=a.get('par', 'utilisateur'))
        return {'sous_etape': sid, 'etat': 'en_cours', 'avant': avant}


VOIES = ('collecte', 'generation', 'mixte')


def cmd_registre(ch, a):
    cle = str(a.get('cle') or '').strip()
    statut = a.get('statut', 'propose')
    if not re.match(r'^[a-z0-9_.-]{1,80}$', cle):
        raise Refus('Clé de règle invalide (minuscules, chiffres, . _ -).')
    if statut not in ('propose', 'fixe'):
        raise Refus("Statut refusé : « propose » ou « fixe » (le scellement d'un seuil se fait au scellement de l'étape 2).")
    citation = str(a.get('citation') or '').strip()
    if not citation:
        raise Refus("Il faut les mots de l'utilisateur (citation).")
    with ch.verrou():
        c = ch.lire()
        sid = a.get('sous_etape')
        if sid:
            sous_etape(c, sid)
        reg = charger_json(ch.chemin('registre.json'), {})
        ancien = reg.get(cle)
        if ancien and ancien.get('statut') == 'scelle':
            raise Refus(f'La règle {cle} est scellée : la changer relance son étape (réouverture explicite).')
        reg[cle] = {'valeur': a.get('valeur'), 'statut': statut, 'citation': citation, 'sous_etape': sid,
                    'libelle': a.get('libelle'), 'a': maintenant(),
                    'historique': ((ancien or {}).get('historique') or []) + ([{k: ancien[k] for k in ('valeur', 'statut', 'citation', 'a')}] if ancien else [])}
        if cle == 'voie.donnees':
            if a.get('valeur') not in VOIES:
                raise Refus(f"voie.donnees : {', '.join(VOIES)}.")
            c['voie_donnees'] = a.get('valeur')
            ch.enregistrer(c)
        ecrire_json(ch.chemin('registre.json'), reg)
        ch.journaliser('registre', cle=cle, valeur=a.get('valeur'), statut=statut, sous_etape=sid)
        return {'cle': cle, 'regle': reg[cle]}


def cmd_evenement(ch, a):
    type_ = str(a.get('type') or '')
    if not re.match(r'^[a-z_]{2,40}$', type_):
        raise Refus('Type d\'événement invalide.')
    donnees = a.get('donnees') or {}
    if not isinstance(donnees, dict):
        raise Refus('donnees doit être un objet.')
    ch.lire()
    return ch.journaliser(type_, **{k: v for k, v in donnees.items() if k not in ('a', 'type')})


# ─── Étape 1 : arbre des définitions (E1.5), relecture à l'aveugle (E1.7), catalogue de l'outil (E1.3.1) ────────

ARBRE = 'etape1/arbre-definitions.json'
ETATS_TERME = ('a_definir', 'redecoupe', 'liste', 'modele')


def lire_arbre(ch):
    return charger_json(ch.chemin(ARBRE), {'termes': []})


def cmd_terme(ch, a):
    """Un terme de l'arbre des définitions : sa couche, son parent, son état (redécoupé, fixé par liste, laissé au modèle)."""
    tid = str(a.get('id') or '').strip()
    if not re.match(r'^[A-Za-z0-9_.-]{1,40}$', tid):
        raise Refus('Identifiant de terme invalide (ex. N1, N2A, N3A).')
    etat = a.get('etat', 'a_definir')
    if etat not in ETATS_TERME:
        raise Refus(f"État de terme refusé : {', '.join(ETATS_TERME)}.")
    libelle = str(a.get('libelle') or '').strip()
    if not libelle:
        raise Refus('Le terme a besoin de son libellé.')
    citation = str(a.get('citation') or '').strip()
    if etat != 'a_definir' and not citation:
        raise Refus("Il faut les mots de l'utilisateur (citation) pour fixer l'état d'un terme.")
    liste = a.get('liste')
    if etat == 'liste' and not (isinstance(liste, list) and liste):
        raise Refus('Un terme fixé par une liste a besoin de sa liste (non vide).')
    with ch.verrou():
        c = ch.lire()
        if c['etapes']['1']['etat'] == 'scellee':
            raise Refus("L'étape 1 est scellée : l'arbre ne change plus sans la rouvrir.")
        arbre = lire_arbre(ch)
        termes = {t['id']: t for t in arbre['termes']}
        parent = a.get('parent')
        if parent:
            if parent not in termes:
                raise Refus(f'Parent inconnu : {parent}. Déclare-le d\'abord.')
            if parent == tid:
                raise Refus('Un terme ne peut pas être son propre parent.')
            couche = termes[parent]['couche'] + 1
        else:
            couche = 1
        t = {'id': tid, 'libelle': libelle, 'definition': a.get('definition'), 'couche': couche, 'parent': parent or None,
             'etat': etat, 'liste': liste if etat == 'liste' else None, 'citation': citation or None, 'a': maintenant()}
        ancien = termes.get(tid)
        if ancien:
            t['historique'] = (ancien.get('historique') or []) + [{k: ancien.get(k) for k in ('libelle', 'etat', 'liste', 'citation', 'a')}]
        termes[tid] = t
        arbre['termes'] = sorted(termes.values(), key=lambda x: (x['couche'], x['id']))
        ecrire_json(ch.chemin(ARBRE), arbre)
        ch.journaliser('terme', id=tid, couche=couche, etat=etat, citation=citation or None)
        return {'terme': t, 'termes': len(arbre['termes'])}


def vue_arbre(ch):
    arbre = lire_arbre(ch)
    reg = charger_json(ch.chemin('registre.json'), {})
    # Les seuils B1/B2 ne se fixent que sur la couche racine : les sous-couches n'en ont pas.
    seuils = {'1': {'b1': (reg.get('b1.couche1') or {}).get('valeur'), 'b2': (reg.get('b2.couche1') or {}).get('valeur')}} if arbre['termes'] else {}
    return {'termes': arbre['termes'], 'seuils': seuils}


def cmd_relecture(ch, a):
    """Dépose les réponses d'un relecteur à l'aveugle (E1.7) : {exemple: {critère: réponse}}. Le relecteur ne voit rien d'autre."""
    try:
        passe = int(a.get('passe'))
    except (TypeError, ValueError):
        passe = None
    relecteur = str(a.get('relecteur') or '')
    if passe not in (1, 2):
        raise Refus('Passe 1 ou 2 (deux passes au plus, puis la décision revient à l\'utilisateur).')
    if not re.match(r'^[A-Z]$', relecteur):
        raise Refus('Relecteur : une lettre majuscule (A, B en passe 1 ; C, D en passe 2).')
    reponses = a.get('reponses')
    if not isinstance(reponses, dict) or not reponses or not all(isinstance(v, dict) for v in reponses.values()):
        raise Refus('reponses : {exemple: {critère: réponse}}, non vide.')
    with ch.verrou():
        c = ch.lire()
        if c['etapes']['1']['etat'] == 'scellee':
            raise Refus("L'étape 1 est scellée.")
        cible = ch.chemin('etape1', 'relecture', f'passe-{passe}', f'relecteur-{relecteur}.json')
        deja = [f for f in os.listdir(os.path.dirname(cible)) if f.startswith('relecteur-')] if os.path.isdir(os.path.dirname(cible)) else []
        if os.path.exists(cible):
            raise Refus(f'Le relecteur {relecteur} a déjà rendu la passe {passe} : un relecteur neuf prend une autre lettre.')
        if len(deja) >= 2:
            raise Refus(f'La passe {passe} a déjà ses deux relecteurs.')
        ecrire_json(cible, {'passe': passe, 'relecteur': relecteur, 'a': maintenant(), 'reponses': reponses})
        ch.journaliser('relecture_deposee', passe=passe, relecteur=relecteur, exemples=len(reponses))
        return {'passe': passe, 'relecteur': relecteur, 'exemples': len(reponses), 'accord': accord(ch, passe)}


def norm(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else v.strip().lower()


def accord(ch, passe):
    """L'accord des deux relecteurs d'une passe, critère par critère, calculé par le programme (E1.7)."""
    d = ch.chemin('etape1', 'relecture', f'passe-{passe}')
    if not os.path.isdir(d):
        return None
    rendus = [charger_json(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.startswith('relecteur-')]
    if len(rendus) < 2:
        return {'passe': passe, 'complet': False, 'relecteurs': [r['relecteur'] for r in rendus]}
    a, b = rendus[0], rendus[1]
    communs = sorted(set(a['reponses']) & set(b['reponses']))
    criteres = sorted({k for e in communs for k in list(a['reponses'][e]) + list(b['reponses'][e])})
    par_critere, desaccords = {}, []
    for k in criteres:
        n = pareil = 0
        for e in communs:
            ra, rb = a['reponses'][e].get(k), b['reponses'][e].get(k)
            if ra is None and rb is None:
                continue
            n += 1
            if ra is not None and rb is not None and norm(ra) == norm(rb):
                pareil += 1
            else:
                desaccords.append({'exemple': e, 'critere': k, a['relecteur']: ra, b['relecteur']: rb})
        par_critere[k] = {'accord': round(pareil / n, 4) if n else None, 'exemples': n, 'garde': n > 0 and pareil == n}
    res = {'passe': passe, 'complet': True, 'relecteurs': [a['relecteur'], b['relecteur']], 'exemples': len(communs),
           'par_critere': par_critere, 'desaccords': desaccords}
    ecrire_json(os.path.join(d, 'accord.json'), res)
    return res


def cmd_accord(ch, a):
    return {'passes': [x for x in (accord(ch, 1), accord(ch, 2)) if x]}


def vue_catalogue(ch):
    """Le catalogue de l'outil (E1.3.1), écran par écran, lu dans etape1/outil/catalogue.tsv (ecran, action, description)."""
    chemin = ch.chemin('etape1', 'outil', 'catalogue.tsv')
    if not os.path.exists(chemin):
        return None
    ecrans = {}
    with open(chemin, encoding='utf-8', errors='replace') as f:
        for i, ligne in enumerate(f):
            morceaux = ligne.rstrip('\n').split('\t')
            if i == 0 and morceaux and morceaux[0].strip().lower() in ('ecran', 'écran'):
                continue
            if len(morceaux) < 2 or not morceaux[0].strip():
                continue
            ecrans.setdefault(morceaux[0].strip(), []).append({'action': morceaux[1].strip(), 'description': (morceaux[2].strip() if len(morceaux) > 2 else '')})
    return {'ecrans': [{'ecran': k, 'actions': v} for k, v in ecrans.items()], 'actions': sum(len(v) for v in ecrans.values())}


# ─── Scellement d'une étape (E1.8, E2.16, E3.3) ──────────────────────────────────────────────────────────


def derniere_sous_etape(c, n):
    return [s for s in actives(c) if s['etape'] == n][-1]


def documents_etape(ch, n):
    base = ch.chemin(f'etape{n}')
    docs = []
    for racine, dossiers, fichiers in os.walk(base):
        dossiers[:] = sorted(d for d in dossiers if not d.startswith('.') and d != '__pycache__')
        for f in sorted(fichiers):
            if f.startswith('.') or f.endswith('.pyc') or f in ('scelle.json', 'demande-scellement.json'):
                continue
            chemin = os.path.join(racine, f)
            docs.append({'chemin': os.path.relpath(chemin, ch.dossier), 'empreinte': empreinte(chemin)})
    return docs


def empreinte_globale(docs, registre_scelle):
    h = hashlib.sha256()
    for d in docs:
        h.update(f"{d['chemin']}\t{d['empreinte']}\n".encode())
    h.update(json.dumps(registre_scelle, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def regles_etape(reg, c, n):
    """Les règles du registre que le scellement de l'étape n verrouille : les seuils de qualité « proposés »
    ne se scellent qu'à l'étape 2 ; à l'étape 1 ils restent proposés."""
    if n != 2:
        return {}
    return {k: {'valeur': r['valeur'], 'citation': r['citation']} for k, r in sorted(reg.items()) if r.get('statut') in ('propose', 'fixe')}


def cmd_sceller(ch, a):
    """Demande le scellement d'une étape : récapitulatif, empreintes, attente de la confirmation sur le téléphone."""
    try:
        n = int(a.get('etape'))
    except (TypeError, ValueError):
        raise Refus('Étape 1 à 5.')
    with ch.verrou():
        c = ch.lire()
        e = c['etapes'].get(str(n))
        if not e:
            raise Refus('Étape 1 à 5.')
        if e['etat'] == 'scellee':
            raise Refus(f"L'étape {n} est déjà scellée.")
        if e['etat'] == 'fermee':
            raise Refus(f"L'étape {n} n'est pas ouverte.")
        derniere = derniere_sous_etape(c, n)
        ouvertes = [s['id'] for s in actives(c) if s['etape'] == n and s['id'] != derniere['id'] and etat_de(c, s['id']) != 'validee']
        if ouvertes:
            raise Refus(f"Scellement refusé : sous-étapes pas encore validées : {', '.join(ouvertes)}.")
        if n == 3:
            # REGLE_BORNE_PREVUE : un calcul posé sur la borne prévue ne se scelle avec le banc que portes figées ; de même
            # un plafond sans la borne des corrigés, tant que ses inversions vers EXÉCUTER ne sont pas comptées
            # (REGLE_INVERSIONS_EXECUTER).
            prevu = (charger_json(ch.chemin('etape2', 'calcul', 'resultat.json')) or {}).get('etiquettes') or {}
            conf = confirmation_portes(ch)
            if (prevu.get('a_confirmer') or prevu.get('inversions_vers_executer')) and (conf or {}).get('etat') != 'figees':
                raise Refus('Scellement refusé : ' + (conf['motif'] if conf else "les portes posées sur la borne prévue ne sont pas figées "
                            "(outil confirmer_portes, après les relectures du plan)") + '.')
        if n == 2:
            majeurs = probleme_majeur_ouvert(ch)
            if majeurs:
                raise Refus(f'Scellement refusé : la vérification indépendante a un problème majeur ni corrigé ni écarté ({majeurs}).')
        docs = documents_etape(ch, n)
        if not docs:
            raise Refus(f"Rien à sceller : le dossier etape{n}/ est vide.")
        reg = charger_json(ch.chemin('registre.json'), {})
        regles = regles_etape(reg, c, n)
        decisions = [d for d in lire_lignes(ch.chemin('decisions.jsonl')) if d['sous_etape'].startswith(f'E{n}.')]
        validations = {s['id']: (c['sous_etapes'].get(s['id']) or {}).get('citation') for s in actives(c) if s['etape'] == n}
        demande = {
            'chantier': ch.nom, 'etape': n, 'a': maintenant(), 'documents': docs, 'regles_scellees': regles,
            'regles_proposees': {k: r['valeur'] for k, r in sorted(reg.items()) if r.get('statut') == 'propose' and k not in regles},
            'decisions': [{k: d.get(k) for k in ('sous_etape', 'point', 'resume', 'citation', 'a')} for d in decisions],
            'validations': validations,
        }
        demande['empreinte'] = empreinte_globale(docs, regles)
        ecrire_json(ch.chemin(f'etape{n}', 'demande-scellement.json'), demande)
        e['etat'] = 'a_sceller'
        c['sous_etapes'][derniere['id']] = dict(c['sous_etapes'].get(derniere['id']) or {}, etat='a_valider', depuis=demande['a'])
        ch.enregistrer(c)
        ch.journaliser('scellement_demande', etape=n, empreinte=demande['empreinte'], documents=len(docs))
        return {'etape': n, 'empreinte': demande['empreinte'], 'documents': docs, 'decisions': demande['decisions'],
                'regles_scellees': regles, 'regles_proposees': demande['regles_proposees'],
                'confirmation': 'par le canal de confirmation : la demande attend ; rien n’est verrouillé avant'}


def probleme_majeur_ouvert(ch):
    """E2.15 : un problème majeur de la vérification reste ouvert tant qu'il n'est ni corrigé ni écarté (verification.json)."""
    v = charger_json(ch.chemin('etape2', 'verification.json'))
    if not v:
        return None
    ouverts = [p.get('id', '?') for p in v.get('points', []) if p.get('niveau') == 'majeur' and p.get('decision') not in ('corrige', 'ecarte')]
    return ', '.join(ouverts) or None


def confirmation_valide(chemin):
    """Une confirmation ne vaut que posée par le compte de confiance (root par défaut), et inscriptible par lui seul."""
    try:
        st = os.stat(chemin)
    except FileNotFoundError:
        return None
    if st.st_uid != UID_CONFIRMATION or st.st_mode & 0o022:
        return {'refus': 'confirmation posée hors du canal de confirmation (propriétaire ou droits)'}
    return charger_json(chemin)


def appliquer_confirmations(ch, c):
    """Applique une confirmation reçue : l'étape est scellée si l'empreinte confirmée est celle de la demande."""
    change = False
    for n in sorted(c['etapes'], key=int):
        e = c['etapes'][n]
        if e['etat'] != 'a_sceller':
            continue
        demande = charger_json(ch.chemin(f'etape{n}', 'demande-scellement.json'))
        conf = confirmation_valide(os.path.join(CONFIRMATIONS, f'{ch.nom}-etape{n}.json'))
        if not demande or not conf:
            continue
        if 'refus' in conf:
            ch.journaliser('confirmation_refusee', etape=int(n), raison=conf['refus'])
            continue
        if conf.get('empreinte') != demande['empreinte']:
            ch.journaliser('confirmation_refusee', etape=int(n), raison='empreinte différente de la demande')
            continue
        # Les fichiers ont-ils bougé depuis la demande ?
        if empreinte_globale(documents_etape(ch, int(n)), demande['regles_scellees']) != demande['empreinte']:
            ch.journaliser('confirmation_refusee', etape=int(n), raison='un document a changé depuis la demande : redemander le scellement')
            e['etat'] = 'ouverte'
            change = True
            continue
        sceller_maintenant(ch, c, int(n), demande, conf)
        change = True
    if change:
        ch.enregistrer(c)
    return change


def sceller_maintenant(ch, c, n, demande, conf):
    t = maintenant()
    scelle = {'etape': n, 'a': t, 'empreinte': demande['empreinte'], 'confirmation': conf, 'documents': demande['documents'],
              'regles_scellees': demande['regles_scellees']}
    ecrire_json(ch.chemin(f'etape{n}', 'scelle.json'), scelle)
    for d in demande['documents']:
        try:
            os.chmod(ch.chemin(d['chemin']), 0o444)
        except OSError:
            pass
    if demande['regles_scellees']:
        reg = charger_json(ch.chemin('registre.json'), {})
        for k in demande['regles_scellees']:
            if k in reg:
                reg[k]['statut'] = 'scelle'
                reg[k]['scelle_le'] = t
        ecrire_json(ch.chemin('registre.json'), reg)
    c['etapes'][str(n)] = {'etat': 'scellee', 'scelle': {'a': t, 'empreinte': demande['empreinte'], 'documents': demande['documents']}}
    for s in actives(c):
        if s['etape'] == n:
            c['sous_etapes'][s['id']] = dict(c['sous_etapes'].get(s['id']) or {}, etat='scellee', scelle_le=t)
    suivante_etape = str(n + 1)
    if suivante_etape in c['etapes'] and c['etapes'][suivante_etape]['etat'] == 'fermee':
        c['etapes'][suivante_etape]['etat'] = 'ouverte'
        premiere = [s for s in actives(c) if s['etape'] == n + 1][0]
        c['sous_etapes'][premiere['id']] = {'etat': 'en_cours', 'depuis': t, 'debut': t}
        ch.journaliser('sous_etape', sous_etape=premiere['id'], etat='en_cours', avant='a_faire')
    ch.journaliser('scellement_confirme', etape=n, empreinte=demande['empreinte'], par=conf.get('par'), canal=conf.get('canal'))


def cmd_rouvrir_etape(ch, a):
    """Rouvre une étape scellée sur la confirmation explicite de l'utilisateur ; les étapes qui en dépendent sont relancées."""
    try:
        n = int(a.get('etape'))
    except (TypeError, ValueError):
        raise Refus('Étape 1 à 5.')
    citation = str(a.get('citation') or '').strip()
    raison = str(a.get('raison') or '').strip()
    if not citation or not raison:
        raise Refus("Rouvrir une étape scellée demande la confirmation explicite de l'utilisateur, mot pour mot (citation), et la raison.")
    if a.get('confirme') is not True:
        raise Refus("Rouvrir une étape scellée relance les étapes suivantes : présente-le à l'utilisateur et passe confirme=true seulement sur son accord explicite.")
    with ch.verrou():
        c = ch.lire()
        e = c['etapes'].get(str(n))
        if not e or e['etat'] not in ('scellee', 'a_sceller'):
            raise Refus(f"L'étape {n} n'est pas scellée.")
        t = maintenant()
        relancees = []
        for m in sorted((int(k) for k in c['etapes']), reverse=True):
            if m < n:
                continue
            em = c['etapes'][str(m)]
            for d in (em.get('scelle') or {}).get('documents', []):
                try:
                    os.chmod(ch.chemin(d['chemin']), 0o644)
                except OSError:
                    pass
            if os.path.exists(ch.chemin(f'etape{m}', 'scelle.json')):
                os.replace(ch.chemin(f'etape{m}', 'scelle.json'), ch.chemin(f'etape{m}', f".scelle-{t.replace(':', '')}.json"))
            if m == n:
                c['etapes'][str(m)] = {'etat': 'ouverte', 'rouverte': t}
                for s in actives(c):
                    if s['etape'] == m:
                        c['sous_etapes'][s['id']] = dict(c['sous_etapes'].get(s['id']) or {}, etat='validee')
                derniere = derniere_sous_etape(c, m)
                c['sous_etapes'][derniere['id']] = {'etat': 'en_cours', 'depuis': t, 'debut': t}
            elif em['etat'] != 'fermee':
                relancees.append(m)
                c['etapes'][str(m)] = {'etat': 'fermee', 'relancee': t}
                for s in visibles(c):
                    if s['etape'] == m:
                        c['sous_etapes'][s['id']] = {'etat': 'a_faire', 'relancee': t}
        conf = ch.chemin('etape3', 'confirmation-portes.json')
        if n <= 2 and os.path.exists(conf):
            # Nouveau calcul à venir : la confirmation (portes figées ou écart qui ferme la fabrication) part avec l'ancien.
            os.replace(conf, ch.chemin('etape3', f".confirmation-portes-{t.replace(':', '')}.json"))
        if n <= 2:
            reg = charger_json(ch.chemin('registre.json'), {})
            for k, r in reg.items():
                if r.get('statut') == 'scelle':
                    r['statut'] = 'propose'
                    r['rescelle_requis'] = t
            ecrire_json(ch.chemin('registre.json'), reg)
        ch.enregistrer(c)
        ch.journaliser('etape_rouverte', etape=n, raison=raison, citation=citation, relancees=relancees)
        return {'etape': n, 'etat': 'ouverte', 'relancees': relancees}


# ─── Mesures : calculées par le programme depuis le journal, jamais résumées par l'agent ──────────────────


def secondes(a, b):
    fa = datetime.datetime.strptime(a, '%Y-%m-%dT%H:%M:%SZ')
    fb = datetime.datetime.strptime(b, '%Y-%m-%dT%H:%M:%SZ')
    return max(0, int((fb - fa).total_seconds()))


def mesures(ch, c, fin=None):
    """Par sous-étape et par étape : durée, attente de la décision de l'utilisateur, jetons, frictions, incidents.
    Une mesure absente vaut None (« non mesuré »), jamais 0."""
    journal = lire_lignes(ch.chemin('journal.jsonl'))
    fin = fin or maintenant()
    par = {}

    def m(sid):
        return par.setdefault(sid, {'duree_s': None, 'attente_utilisateur_s': None, 'echanges': 0, 'temps_reponse_s': [],
                                     'decisions': 0, 'autre_chose': 0, 'reouvertures': 0, 'raisons_reouverture': [],
                                     'jetons_entree': None, 'jetons_sortie': None, 'tours': 0, 'incidents': 0})

    debut, attente_depuis, courante, comptes = {}, {}, None, {}
    for ev in journal:
        t, typ, sid = ev['a'], ev['type'], ev.get('sous_etape')
        if typ == 'sous_etape' and sid:
            x = m(sid)
            if ev.get('etat') == 'en_cours':
                debut.setdefault(sid, t)
                courante = sid
            if ev.get('etat') == 'a_valider':
                attente_depuis[sid] = t
            if ev.get('etat') == 'validee':
                if sid in debut:
                    x['duree_s'] = (x['duree_s'] or 0) + secondes(debut.pop(sid), t)
                if sid in attente_depuis:
                    x['attente_utilisateur_s'] = (x['attente_utilisateur_s'] or 0) + secondes(attente_depuis.pop(sid), t)
        elif typ == 'sous_etape_rouverte' and sid:
            x = m(sid)
            x['reouvertures'] += 1
            x['raisons_reouverture'].append(ev.get('raison'))
            debut.setdefault(sid, t)
            courante = sid
        elif typ == 'message_utilisateur':
            x = m(sid or courante or '?')
            x['echanges'] += 1
            if ev.get('temps_reponse_s') is not None:
                x['temps_reponse_s'].append(ev['temps_reponse_s'])
        elif typ == 'decision' and sid:
            x = m(sid)
            x['decisions'] += 1
            if ev.get('option') in ('D', 'autre'):
                x['autre_chose'] += 1
        elif typ == 'tour_termine':
            x = m(courante or '?')
            x['tours'] += 1
            compte = ev.get('compte') or 'inconnu'
            jc = comptes.setdefault(compte, {'jetons_entree': 0, 'jetons_sortie': 0, 'tours': 0})
            jc['tours'] += 1
            jc['jetons_entree'] += (ev.get('jetons_entree') or 0) + (ev.get('jetons_cache_lus') or 0) + (ev.get('jetons_cache_ecrits') or 0)
            jc['jetons_sortie'] += ev.get('jetons_sortie') or 0
            if ev.get('jetons_entree') is not None:
                entree = ev['jetons_entree'] + (ev.get('jetons_cache_lus') or 0) + (ev.get('jetons_cache_ecrits') or 0)
                x['jetons_entree'] = (x['jetons_entree'] or 0) + entree
            if ev.get('jetons_sortie') is not None:
                x['jetons_sortie'] = (x['jetons_sortie'] or 0) + ev['jetons_sortie']
        elif typ in ('agent_panne', 'programme_panne', 'incident'):
            m(sid or courante or '?')['incidents'] += 1
        elif typ == 'scellement_confirme':
            courante = None
    # Ce qui tourne encore : durée jusqu'à maintenant, marquée en cours.
    for sid, t in debut.items():
        x = m(sid)
        x['duree_s'] = (x['duree_s'] or 0) + secondes(t, fin)
        x['en_cours'] = True
    for sid, t in attente_depuis.items():
        x = m(sid)
        x['attente_utilisateur_s'] = (x['attente_utilisateur_s'] or 0) + secondes(t, fin)
    for x in par.values():
        tr = x.pop('temps_reponse_s')
        x['temps_reponse_median_s'] = sorted(tr)[len(tr) // 2] if tr else None
        x['part_autre_chose'] = round(x['autre_chose'] / x['decisions'], 3) if x['decisions'] else None
    etapes = {}
    for sid, x in par.items():
        if not re.match(r'^E\d', sid):
            continue
        n = sid[1]
        e = etapes.setdefault(n, {'duree_s': None, 'attente_utilisateur_s': None, 'echanges': 0, 'decisions': 0, 'autre_chose': 0,
                                  'reouvertures': 0, 'jetons_entree': None, 'jetons_sortie': None, 'tours': 0, 'incidents': 0})
        for k in e:
            if x.get(k) is not None:
                e[k] = (e[k] or 0) + x[k]
    autres = sum(1 for ev in journal if ev['type'] not in TYPES_CONNUS)
    return {'sous_etapes': par, 'etapes': etapes, 'evenements': len(journal), 'autres': autres, 'comptes': comptes,
            'non_mesure': ['énergie (relevés des postes à brancher)', 'coût des API externes (lot 5)']}


TYPES_CONNUS = {'usage_importe', 'usage_vu_pour_etiquetage', 'usage_etiquete', 'usage_juge', 'usage_renouvele', 'bibliotheque_lue', 'audit_porte', 'verification_contexte', 'chantier_cree', 'chantier_repris', 'sous_etape', 'sous_etape_rouverte', 'message_utilisateur', 'decision', 'tour_termine',
                'agent_panne', 'programme_panne', 'incident', 'scellement_demande', 'scellement_confirme', 'confirmation_refusee',
                'etape_rouverte', 'sortie_ecrite', 'registre', 'categorie', 'terme', 'relecture_deposee', 'session_detachee',
                'agent', 'agent_fini', 'agent_arrete', 'compte_brancher', 'compte_debrancher', 'depense_prevoir', 'depense_accepter',
                'depense_depenser', 'depense_arretee', 'calcul_etape2', 'portes_figees', 'fabrication_fermee', 'relecture_utilisateur', 'controle_tableau', 'sollicitation_traitee', 'agent_relance'}


def cmd_mesures(ch, a):
    with ch.verrou():
        c = ch.lire()
    return mesures(ch, c)


# ─── Moteur : comptes Claude des agents, agents, dépenses ──────────────────────────────────────────────────────────

RELEVE_COMPTES = REGLAGES['releve_comptes']   # URL, fichier JSON ou '' (réglage releve_comptes)
FINS = REGLAGES['agents']['dossier_fins']   # <nom>.fin : « code heure », écrit par le lanceur à la fin d'un agent
RELANCES_MAX = 3
RELANCE_ESPACEMENT_S = 15 * 60
MUET_S = 20 * 60   # un agent « travaille » sans activité depuis ce délai est tenu pour bloqué
SEUIL_ORANGE_SEMAINE = 85
SEUIL_ORANGE_5H = 90
NOM_AGENT = re.compile(r'^[a-z0-9][a-z0-9-]{2,39}$')


def lire_releve(url=None):
    """Le relevé des comptes : une URL, un fichier JSON, ou la liste `comptes` des réglages (sans quota)."""
    source = url or RELEVE_COMPTES
    if not source:
        return {'comptes': [dict(c, ok=True) for c in REGLAGES['comptes']], 'sessions': []}
    try:
        if source.startswith(('http://', 'https://')):
            import urllib.request
            with urllib.request.urlopen(source, timeout=8) as r:
                return json.load(r)
        with open(os.path.expanduser(source), encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:  # relevé injoignable : dit tel quel, jamais inventé
        return {'erreur': str(e)[:200], 'comptes': [], 'sessions': []}


def orange(compte):
    s = (compte.get('semaine') or {}).get('pct')
    h = (compte.get('h5') or {}).get('pct')
    return (s is not None and s >= SEUIL_ORANGE_SEMAINE) or (h is not None and h >= SEUIL_ORANGE_5H)


def choisir_compte(branches, releve, voulu=None):
    """Le compte d'un agent : celui que l'utilisateur choisit, sinon le branché qui a le plus de quota de la semaine,
    en écartant les comptes proches de leur limite (orange) tant qu'un autre est disponible."""
    par_id = {c['id']: c for c in releve.get('comptes', []) if c.get('ok', True)}
    candidats = [par_id[b] for b in branches if b in par_id]
    if voulu:
        if voulu not in branches:
            raise Refus(f"Le compte {voulu} n'est pas branché au chantier (branchés : {', '.join(branches) or 'aucun'}).")
        c = par_id.get(voulu)
        return {'compte': voulu, 'raison': 'choisi par toi', 'orange': bool(c and orange(c))}
    if not candidats:
        raise Refus('Aucun compte branché au Moteur avec un relevé de quota : branche un compte (outil comptes).')
    verts = [c for c in candidats if not orange(c)] or candidats
    meilleur = min(verts, key=lambda c: ((c.get('semaine') or {}).get('pct') or 0, (c.get('h5') or {}).get('pct') or 0))
    raison = 'le plus de quota de la semaine' + (' (tous les comptes sont proches de leur limite)' if verts is candidats and all(orange(c) for c in candidats) else '')
    ecartes = [c['id'] for c in candidats if orange(c) and c is not meilleur]
    return {'compte': meilleur['id'], 'raison': raison, 'ecartes_orange': ecartes, 'orange': orange(meilleur)}


def cmd_comptes(ch, a):
    """Brancher ou débrancher un compte Claude au Moteur du chantier ; sans action, l'état des comptes branchés et de leurs agents."""
    action = a.get('action', 'voir')
    with ch.verrou():
        c = ch.lire()
        branches = list(c.get('comptes') or [])
        if action in ('brancher', 'debrancher'):
            cid = str(a.get('compte') or '').strip()
            if not re.match(r'^[a-z0-9-]{2,30}$', cid):
                raise Refus('Compte invalide (ex. compte-a, compte-b).')
            if action == 'brancher' and cid not in branches:
                branches.append(cid)
            if action == 'debrancher' and cid in branches:
                branches.remove(cid)
            c['comptes'] = branches
            ch.enregistrer(c)
            ch.journaliser('compte_' + action, compte=cid)
        elif action != 'voir':
            raise Refus('Action : voir, brancher ou debrancher.')
    return {'branches': branches}


def lire_agents(ch):
    d = ch.chemin('agents')
    if not os.path.isdir(d):
        return []
    return [charger_json(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith('.json')]


def cmd_agent(ch, a):
    """La fiche d'un agent qui travaille pour le chantier : qui il est, sur quoi, depuis quand, où il en est, sur quel compte."""
    nom = str(a.get('nom') or '')
    if not NOM_AGENT.match(nom):
        raise Refus('Nom d\'agent invalide (minuscules, chiffres, tirets, 3 à 40).')
    etat = a.get('etat', 'travaille')
    if etat not in ('travaille', 'attend', 'fini', 'panne', 'arrete'):
        raise Refus('État : travaille, attend, fini, panne ou arrete.')
    with ch.verrou():
        c = ch.lire()
        chemin = ch.chemin('agents', f'{nom}.json')
        fiche = charger_json(chemin) or {'nom': nom, 'depuis': maintenant(), 'relances': 0}
        for k in ('role', 'sous_etape', 'quoi', 'compte', 'ou', 'session', 'lien', 'ou_en_est', 'genre', 'relance'):
            if a.get(k) is not None:
                fiche[k] = a[k]
        if fiche.get('sous_etape'):
            sous_etape(c, fiche['sous_etape'])
        if fiche.get('relance') is not None and not (isinstance(fiche['relance'], list) and fiche['relance'] and all(isinstance(x, str) for x in fiche['relance'])):
            raise Refus('relance : la commande qui relance ce travail, en liste (ex. ["./lancer-agent.sh", "nom", "consigne.md"]).')
        if not fiche.get('role'):
            raise Refus("Dis le rôle de l'agent (ex. rédacteur des définitions, relecteur A).")
        if not fiche.get('compte') and fiche.get('genre', 'agent') == 'agent':
            choix = choisir_compte(c.get('comptes') or [], lire_releve() if a.get('releve') is None else a['releve'], a.get('compte_voulu'))
            fiche['compte'], fiche['choix_compte'] = choix['compte'], choix
        avant = fiche.get('etat')
        fiche['etat'] = etat
        fiche['maj'] = maintenant()
        if etat == 'panne' and avant != 'panne':
            fiche['relances'] = fiche.get('relances', 0)
        ecrire_json(chemin, fiche)
        if avant != etat:
            ch.journaliser({'fini': 'agent_fini', 'panne': 'agent_panne', 'arrete': 'agent_arrete'}.get(etat, 'agent'), nom=nom,
                           sous_etape=fiche.get('sous_etape'), etat=etat, compte=fiche.get('compte'), role=fiche.get('role'))
        return fiche


def vue_agents(ch, releve):
    """Les fiches, enrichies du relevé (état réel de la session, dernière action, lien de sa conversation)."""
    sessions = {}
    for s in releve.get('sessions', []):
        sessions[s.get('id', '').split(':', 1)[-1]] = s
    out = []
    for f in lire_agents(ch):
        s = sessions.get(f.get('session') or f'claude-{f["nom"]}')
        if s and f.get('etat') not in ('fini', 'arrete'):
            f = dict(f, etat_session=s.get('etat'), action=s.get('action'), activite=s.get('activite'), lien=f.get('lien') or s.get('lien'))
        out.append(f)
    return out


def vue_comptes(c, releve, agents):
    branches = c.get('comptes') or []
    out = []
    for cpt in releve.get('comptes', []):
        if cpt['id'] not in branches:
            continue
        out.append({'id': cpt['id'], 'nom': cpt.get('nom', cpt['id']), 'h5': (cpt.get('h5') or {}).get('pct'),
                    'semaine': (cpt.get('semaine') or {}).get('pct'), 'orange': orange(cpt),
                    'agents': [a['nom'] for a in agents if a.get('compte') == cpt['id'] and a.get('etat') in ('travaille', 'attend', 'panne')]})
    manquants = [b for b in branches if b not in {x['id'] for x in out}]
    connus = [{'id': cpt['id'], 'nom': cpt.get('nom', cpt['id'])} for cpt in releve.get('comptes', []) if cpt['id'] not in branches]
    return {'branches': branches, 'comptes': out, 'sans_releve': manquants, 'erreur': releve.get('erreur'), 'connus': connus}


def constater_fins(ch):
    """Un agent dont le lanceur a écrit <nom>.fin a fini (code 0) ou s'est arrêté en panne (autre code) : constaté
    par le programme, sans attendre que l'agent le déclare."""
    changes = []
    for f in lire_agents(ch):
        if f.get('etat') not in ('travaille', 'attend') or f.get('genre') == 'programme':
            continue
        fin = os.path.join(FINS, f['nom'] + '.fin')
        if not os.path.exists(fin) or os.path.getmtime(fin) < datetime.datetime.strptime(f['depuis'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp():
            continue
        try:
            with open(fin, encoding='utf-8') as fd:
                code = int(fd.read().split()[0])
        except (ValueError, IndexError, OSError):
            code = 1
        etat = 'fini' if code == 0 else 'panne'
        cmd_agent(ch, {'chantier': ch.nom, 'nom': f['nom'], 'etat': etat, 'ou_en_est': 'a fini' if code == 0 else f'arrêté (code {code})'})
        changes.append({'nom': f['nom'], 'etat': etat})
    return changes


def cmd_relancer(ch, a):
    """Relance un travail bloqué ou en panne, par sa commande de relance, au plus 3 fois, espacées de 15 min."""
    import subprocess
    nom = str(a.get('nom') or '')
    with ch.verrou():
        chemin = ch.chemin('agents', f'{nom}.json')
        f = charger_json(chemin)
        if not f:
            raise Refus(f'Agent inconnu : {nom}.')
        if not f.get('relance'):
            raise Refus(f"{nom} n'a pas de commande de relance : préviens l'utilisateur.")
        if f.get('relances', 0) >= RELANCES_MAX:
            raise Refus(f'{nom} a déjà été relancé {RELANCES_MAX} fois : la décision revient à l’utilisateur.')
        if f.get('derniere_relance') and secondes(f['derniere_relance'], maintenant()) < RELANCE_ESPACEMENT_S:
            raise Refus(f'{nom} vient d’être relancé : on attend avant de recommencer.')
        try:
            os.remove(os.path.join(FINS, nom + '.fin'))
        except OSError:
            pass
        subprocess.Popen(f['relance'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        t = maintenant()
        f.update(etat='travaille', relances=f.get('relances', 0) + 1, derniere_relance=t, depuis=t, ou_en_est='relancé')
        ecrire_json(chemin, f)
        ch.journaliser('agent_relance', nom=nom, relances=f['relances'], sous_etape=f.get('sous_etape'))
        return f


def cmd_suivi(ch, a):
    """Agents et comptes du chantier, avec le relevé des comptes ."""
    c = ch.lire()
    constater_fins(ch)
    releve = a.get('releve') if isinstance(a.get('releve'), dict) else lire_releve()
    agents = vue_agents(ch, releve)
    fin = maintenant()
    for ag in agents:
        muet = ag.get('etat') == 'travaille' and ag.get('activite') and (age_s(str(ag['activite'])[:19] + 'Z', fin) or 0) > MUET_S
        ag['bloque'] = bool(ag.get('etat') == 'panne' or muet)
        ag['relancable'] = bool(ag['bloque'] and ag.get('relance') and ag.get('relances', 0) < RELANCES_MAX)
    return {'agents': agents, 'comptes': vue_comptes(c, releve, agents), 'budget': budget(ch)}


def budget(ch):
    b = charger_json(ch.chemin('budget.json'), {'passes': []})
    tot = {'prevu_eur': 0.0, 'valide_eur': 0.0, 'depense_eur': 0.0, 'quota_prevu_pct': 0.0, 'quota_valide_pct': 0.0}
    for p in b['passes']:
        tot['prevu_eur'] += p.get('cout_estime_eur') or 0
        tot['quota_prevu_pct'] += p.get('quota_pct') or 0
        if p.get('accord'):
            tot['valide_eur'] += p.get('montant_accepte_eur') or 0
            tot['quota_valide_pct'] += p.get('quota_pct') or 0
        tot['depense_eur'] += p.get('depense_eur') or 0
    return dict({k: round(v, 4) for k, v in tot.items()}, passes=b['passes'])


def cmd_depense(ch, a):
    """une passe payante est prévue (devis), acceptée par l'utilisateur (mot pour mot, montant accepté),
    puis dépensée ; une passe qui dépasse le montant accepté s'arrête et revient vers l'utilisateur."""
    action = a.get('action')
    pid = str(a.get('passe') or '').strip()
    if not re.match(r'^[a-z0-9-]{2,60}$', pid):
        raise Refus('Identifiant de passe invalide (ex. pilote-generation).')
    with ch.verrou():
        c = ch.lire()
        b = charger_json(ch.chemin('budget.json'), {'passes': []})
        passes = {p['id']: p for p in b['passes']}
        p = passes.get(pid)
        if action == 'prevoir':
            champs = ('role', 'fournisseur', 'modele', 'relectures_par_donnee', 'cout_unitaire_eur', 'cout_estime_eur', 'duree_estimee', 'quota_pct', 'sous_etape')
            manque = [k for k in ('role', 'fournisseur', 'modele', 'cout_estime_eur') if a.get(k) is None]
            if manque:
                raise Refus(f"Rien n'est présenté à valider sans ses chiffres : manque {', '.join(manque)}.")
            if a.get('sous_etape'):
                sous_etape(c, a['sous_etape'])
            p = dict(p or {}, id=pid, **{k: a.get(k) for k in champs}, prevu_le=maintenant())
            p.pop('accord', None)
        elif action == 'accepter':
            if not p:
                raise Refus(f'Passe inconnue : {pid}. Présente-la d\'abord (action prevoir).')
            citation = str(a.get('citation') or '').strip()
            if not citation:
                raise Refus("L'accord se donne dans le chat : il faut la réponse de l'utilisateur, mot pour mot.")
            montant = a.get('montant_accepte_eur', p.get('cout_estime_eur'))
            p.update(accord={'citation': citation, 'a': maintenant()}, montant_accepte_eur=montant)
        elif action == 'depenser':
            ferme = fabrication_fermee(ch)
            if ferme:
                raise Refus(f'Fabrication fermée : {ferme}.')
            if not p or not p.get('accord'):
                raise Refus(f"Aucune dépense sans l'accord de l'utilisateur : la passe {pid} n'est pas acceptée.")
            montant = float(a.get('montant_eur') or 0)
            nouveau = (p.get('depense_eur') or 0) + montant
            if nouveau > (p.get('montant_accepte_eur') or 0) + 1e-9:
                p['arretee'] = {'a': maintenant(), 'depense_eur': p.get('depense_eur') or 0, 'demande_eur': montant}
                passes[pid] = p
                b['passes'] = list(passes.values())
                ecrire_json(ch.chemin('budget.json'), b)
                ch.journaliser('depense_arretee', passe=pid, depense_eur=p.get('depense_eur') or 0, accepte_eur=p.get('montant_accepte_eur'))
                raise Refus(f"Dépassement : la passe {pid} atteindrait {nouveau:.2f} € pour {p.get('montant_accepte_eur')} € acceptés ; elle s'arrête et revient vers l'utilisateur.")
            p['depense_eur'] = round(nouveau, 6)
        else:
            raise Refus('Action : prevoir, accepter ou depenser.')
        passes[pid] = p
        b['passes'] = list(passes.values())
        ecrire_json(ch.chemin('budget.json'), b)
        ch.journaliser('depense_' + action, passe=pid, montant_eur=a.get('montant_eur') or a.get('montant_accepte_eur') or a.get('cout_estime_eur'),
                       citation=a.get('citation'))
        return {'passe': p, 'budget': {k: v for k, v in budget(ch).items() if k != 'passes'}}



def cmd_arreter_agent(ch, a):
    """Arrêter un travail depuis le volet : la session tmux de l'agent, par son nom exact, jamais par motif."""
    import subprocess
    nom = str(a.get('nom') or '')
    with ch.verrou():
        fiche = charger_json(ch.chemin('agents', f'{nom}.json'))
    if not fiche:
        raise Refus(f'Agent inconnu : {nom}.')
    session = fiche.get('session') or f'claude-{nom}'
    arret = 'non tenté'
    if (fiche.get('ou') or 'ici') == 'ici':
        r = subprocess.run(['tmux', 'kill-session', '-t', '=' + session], capture_output=True, text=True)
        arret = 'session arrêtée' if r.returncode == 0 else f"session introuvable ({r.stderr.strip()[:80]})"
    else:
        arret = f"session sur {fiche.get('ou')} : arrêt à faire sur ce poste"
    f = cmd_agent(ch, {'chantier': ch.nom, 'nom': nom, 'etat': 'arrete', 'ou_en_est': f'arrêté depuis le volet ({arret})'})
    return dict(f, arret=arret)


# ─── Étape 2 : lexique des notions comprises, calcul des quantités (E2.4-E2.14) ─────────────────────────────────


def methode(reg):
    m = charger_json(os.path.join(ICI, 'methode.json'))
    m.pop('greffes_h2', None)   # règles des greffes Harness² : hors du calcul de l'étape 2, lues par greffes()
    for k in ('risque', 'puissance', 'selection_fraction', 'consultations', 'tentatives_examen', 'fenetre_n', 'minimum_essais',
              'filtre_chance_vise', 'filtre_chance_barre'):
        r = reg.get(f'calcul.{k}')
        if r is not None:
            m[k] = r['valeur']
    return m


def greffes():
    """Les règles des greffes Harness², section « greffes_h2 » de methode.json."""
    return (charger_json(os.path.join(ICI, 'methode.json')) or {}).get('greffes_h2') or {}


def valeur(reg, cle, defaut=None, obligatoire=True):
    r = reg.get(cle)
    if r is None or r.get('valeur') is None:
        if obligatoire and defaut is None:
            raise Refus(f'Il manque au registre : {cle}.')
        return defaut
    return r['valeur']


LOTS_CALCUL = ('selection', 'pre_evaluation', 'examen', 'verification')
NOTE_FILTRES = ("filtre (calcul.portes_filtres) : franchi si la note atteint le seuil de la porte 3, même fraction, sur ce "
                "lot ; il ne prouve rien au niveau prédit et ne garantit pas la livraison, que la porte 3 (examen ET "
                "vérification) porte seule. Il évite de brûler une tentative d'examen ; la sélection, consultée à chaque "
                "essai, flatte le meilleur essai : un faux passage coûte une tentative, jamais la garantie")
LOTS_LIVRAISON = ('examen', 'verification')
# Les lots du TEST, ceux que les portes 2 et 3 lisent (examen blanc, examen, vérification) : le plan de fiabilité par
# sortie (registre etiquettes.plan_par_sortie) ne tire ses relectures que là.
LOTS_TEST = ('pre_evaluation', 'examen', 'verification')


def marge_du_critere(marge, c):
    """La marge des corrigés d'un critère : une valeur unique, ou (plan de fiabilité par sortie, confirmer_portes) la
    borne de la sortie que le critère compte ({sortie: borne})."""
    if not c['etiquettes']:
        return 0.0
    return float(marge[c['compte_sur']]) if isinstance(marge, dict) else float(marge or 0.0)


def _par_sortie(reg, cle, cle_repli, sorties):
    """La barre (ou le niveau visé) de chaque sortie : registre <cle>.par_sortie, sinon la valeur unique <cle_repli>
    (repli des chantiers qui n'ont qu'une barre) appliquée à chaque sortie."""
    par = valeur(reg, cle, None, obligatoire=False)
    if par is None:
        v = float(valeur(reg, cle_repli))
        return {u: v for u in sorties}
    manque = [u for u in sorties if u not in par]
    if manque:
        raise Refus(f"{cle} ne donne rien pour la sortie {', '.join(manque)} (sorties du pilote : {', '.join(sorties)}).")
    return {u: float(par[u]) for u in sorties}


def criteres_portes(reg, sorties):
    """Les critères que les portes lisent (fiche de notation de l'étape 1, § 6), un test par critère, jamais sur le
    mélange des sorties :
    • justesse de chaque sortie contre SA barre, dimensionnée sur SON niveau visé ;
    • plafond d'exécution à tort, sur chacune de ses strates (la pire des strates contre la barre = chaque strate passe) ;
    • B1 de la couche racine, lu sur les données « fait » ou à proposition imposée par une règle du code (§ 4.4) :
      jamais sur NE_RIEN_FAIRE. La part imposée de SUGGÉRER n'est connue qu'à la fabrication : la taille requise par B1
      est portée par la sortie dont toutes les données entrent dans sa réserve (EXÉCUTER) ; les données imposées de
      SUGGÉRER s'y ajoutent à la lecture (plus de données : même risque, plus de puissance).
    Toutes les mesures sont des taux de réussite (le plafond : la part des données de la strate que le modèle n'exécute pas).
    `etiquettes` : la borne d'erreur des corrigés s'ajoute à la barre (voir cmd_calcul)."""
    barres = _par_sortie(reg, 'barre.par_sortie', 'barre.qualite', sorties)
    vises = _par_sortie(reg, 'niveau_vise.par_sortie', 'niveau_vise.qualite', sorties)
    cs = []
    for u in sorties:
        if not 0 < barres[u] < vises[u] <= 1:
            raise Refus(f'Sortie {u} : il faut 0 < barre < niveau visé ≤ 1.')
        cs.append({'id': f'justesse:{u}', 'libelle': f'justesse {u}', 'genre': 'justesse', 'compte_sur': u, 'touche': [u],
                   'barre': barres[u], 'vise': vises[u], 'etiquettes': True, 'exact': False})
    pl = valeur(reg, 'plafond.executer_a_tort', None, obligatoire=False)
    if pl is not None:
        b, v = float(pl['barre']), float(pl['vise'])
        if not 0 <= v < b < 1:
            raise Refus('plafond.executer_a_tort : il faut 0 ≤ visé < barre < 1.')
        # Clé plafond.executer_a_tort.borne_corriges (plafond testé sans la borne des corrigés) :
        # false = le plafond est testé SANS la borne des corrigés (barre testée 1 − barre) ; le risque n2 est alors couvert
        # par la relecture de fiabilité, qui compte à part les inversions vers EXÉCUTER (REGLE_INVERSIONS_EXECUTER,
        # cmd_confirmer_portes). Défaut true : la borne s'ajoute, comme en v5.
        borne_c = valeur(reg, 'plafond.executer_a_tort.borne_corriges', True, obligatoire=False)
        if not isinstance(borne_c, bool):
            raise Refus('plafond.executer_a_tort.borne_corriges : true ou false.')
        for s in pl.get('strates') or []:
            if s not in sorties:
                raise Refus(f'plafond.executer_a_tort : strate {s} absente des sorties du pilote.')
            # Le plafond est dimensionné à ses vrais niveaux dans les deux façons (« exact ») : centrer 2 % et 0,5 % sur
            # 1/2 (façon prudente des justesses) prêterait à la mesure une variance qu'un taux de quelques pour cent
            # n'a pas (exemple chiffré : risque 2,5 % par lot, 8 767 données par strate au lieu de 436).
            # Il reçoit la borne des corrigés comme les justesses :
            # un corrigé EXÉCUTER qui serait vraiment NE RIEN FAIRE (ou SUGGÉRER) cache une exécution à tort que la
            # strate ne voit pas, et la tolérance des étiquettes en admet ; la barre testée est donc 1 − barre − borne.
            # Sauf clé borne_corriges à false : barre testée 1 − barre, inversions vers EXÉCUTER bornées à l'étape 3.
            cs.append({'id': f'plafond:{s}', 'libelle': f'exécution à tort sur {s}', 'genre': 'plafond', 'compte_sur': s,
                       'touche': [s], 'barre': round(1 - b, 10), 'vise': round(1 - v, 10), 'etiquettes': borne_c, 'exact': True,
                       'taux_barre': b, 'taux_vise': v, 'borne_corriges': borne_c})
    b1 = valeur(reg, 'b1.couche1', None, obligatoire=False)
    if isinstance(b1, (int, float)) and 0 < b1 < 1:
        reserve = [u for u in sorties if u != 'NE_RIEN_FAIRE']
        porteuse = 'EXECUTER' if 'EXECUTER' in sorties else reserve[0] if reserve else None
        if porteuse is not None:
            vb = float(valeur(reg, 'niveau_vise.b1', vises[porteuse], obligatoire=False))
            if not b1 < vb <= 1:
                raise Refus('B1 : il faut barre (b1.couche1) < niveau visé (niveau_vise.b1, sinon celui de la sortie porteuse).')
            cs.append({'id': 'b1', 'libelle': 'B1 (commande de tête)', 'genre': 'b1', 'compte_sur': porteuse, 'touche': reserve,
                       'barre': float(b1), 'vise': vb, 'etiquettes': True, 'exact': False})
    return cs


def _chance(n, q, k):
    """P[Bin(n, q) ≥ k] : la chance qu'un modèle au vrai niveau q franchisse un test de n données au seuil k."""
    import statistiques as st
    return st.queue(n, min(max(q, 0.0), 1.0), k) if k <= n else 0.0


def niveau_du_profil(c, profil):
    """Le vrai niveau (taux de réussite) d'un modèle décrit par un profil, pour le critère c :
    profil = {sorties: {sortie: justesse}, executer_a_tort: taux (ou {strate: taux}), b1: niveau (défaut : sortie porteuse)}."""
    if c['genre'] == 'justesse':
        return profil['sorties'][c['compte_sur']]
    if c['genre'] == 'plafond':
        t = profil.get('executer_a_tort', c['taux_vise'])
        return 1 - (t.get(c['compte_sur'], c['taux_vise']) if isinstance(t, dict) else t)
    return profil.get('b1', profil['sorties'][c['compte_sur']])


def chance_profil(d, profil, lots=LOTS_CALCUL):
    """Chance qu'un modèle de ce profil franchisse toutes les portes de ces lots : produit, critère par critère et lot par
    lot, des chances de chaque test (lots indépendants, données indépendantes)."""
    detail, total = {}, 1.0
    for c in d['criteres']:
        q = niveau_du_profil(c, profil)
        p = 1.0
        for lot in lots:
            x = d['portes_par_critere'][c['id']]['lots'][lot]
            p *= _chance(x['n'], q, x['k'])
        detail[c['id']] = round(p, 4)
        total *= p
    return round(total, 4), detail


def _k_filtre(t, n):
    """Seuil d'un filtre de n données à la fraction t (celle de la porte 3) : au moins k réussites."""
    return math.ceil(t * n - 1e-9)


PARTS = 40   # finesse du partage de la puissance entre sorties (1/40 du logarithme de la cible)


def _partager(sorties, cout, parts=PARTS):
    """Partage d'une chance cible entre sorties au moindre volume : cout[u][j] = la plus petite taille qui donne à la
    sortie u la part j/parts du logarithme de la cible (None : impossible). Programmation dynamique sur les parts (au
    moins une par sortie) ; rend {sortie: taille}. Le produit des chances des sorties atteint alors la cible."""
    meilleur = {0: (0, {})}
    for i, u in enumerate(sorties):
        reste = len(sorties) - i - 1
        suivant = {}
        for j0, (c0, a0) in meilleur.items():
            for j in range(1, parts - j0 - reste + 1):
                n = cout[u][j]
                if n is None:
                    continue
                t = j0 + j
                if t not in suivant or c0 + n < suivant[t][0]:
                    suivant[t] = (c0 + n, {**a0, u: n})
        meilleur = suivant
    if parts not in meilleur:
        return None
    return meilleur[parts][1]


def _tailles_filtres(st, *, criteres, sorties, alphas, puissance, marge_dim, marge_seuil, dem, fixe_plancher, filtres, tailles_de, selection_de):
    """Option du registre calcul.portes_filtres (vrai) : les tailles quand les portes 1 et 2 sont des FILTRES.

    • Livraison (porte 3, examen ET vérification, chaque critère, risque / tentatives par lot, borne des corrigés) :
      seule à porter la garantie (test d'intersection-union, Berger 1982). Ses tailles sont faites pour qu'un modèle au
      niveau visé de chaque critère soit livré avec la puissance de la méthode (produit des chances des tests de la
      porte 3), la puissance étant partagée entre sorties au moindre volume (_partager), sans descendre sous le
      plancher de chaque test à la façon choisie.
    • Filtres (porte 1 sur la sélection, porte 2 sur l'examen blanc) : le seuil de la porte 3, même fraction. Ils ne
      prouvent rien au niveau prédit : ils évitent de brûler une tentative d'examen. Un filtre qu'on peut ignorer ne
      change pas le risque du test final, puisque les lots sont disjoints (règle « non contraignante » des arrêts pour
      futilité des essais cliniques séquentiels). Leur taille, le même nombre de données pour les deux, est la plus
      petite qui donne : (a) une chance qu'un modèle au niveau visé de chaque critère franchisse le filtre d'au moins
      filtres.chance_vise (produit sur les critères, partagé entre sorties au moindre volume) ; (b) pour chaque
      critère, une chance qu'un modèle à la barre de ce critère franchisse le test d'au plus filtres.chance_barre.
      Le seuil étant au-dessus de la barre, (b) est presque toujours acquis : la médiane d'une binomiale est ⌊np⌋ ou
      ⌈np⌉ (Kaas et Buhrman, 1980). Il ne joue que sur un tout petit lot.
    • Un examen plus grand abaisse le seuil de la porte 3, donc celui des filtres, qui coûtent alors moins : on essaie
      plusieurs tailles d'examen par sortie (descente coordonnée) et l'on garde le total le plus petit.
    Rend (dem, fixe) : les tailles demandées par lot et par sortie, et ce qui les fixe."""
    lp = math.log(puissance)
    lf = math.log(filtres['chance_vise'])
    cap = filtres['chance_barre']

    def k3(c, n, lot, marge):
        p = c['barre'] + marge_du_critere(marge, c)
        return st.critique(n, p, alphas[lot]) if p < 1 else n + 1

    def log_ch(n, q, k):
        x = _chance(n, q, k)
        return math.log(x) if x > 0 else -math.inf

    cu = {u: [c for c in criteres if c['compte_sur'] == u] for u in sorties}
    plancher3 = {u: max(dem[lot][u] for lot in LOTS_LIVRAISON) for u in sorties}

    def g3(u, n):
        return sum(log_ch(n, c['vise'], k3(c, n, lot, marge_dim)) for c in cu[u] for lot in LOTS_LIVRAISON)

    cout3 = {u: [None] + [st.plus_petit_n(lambda n, u=u, j=j: g3(u, n) >= j / PARTS * lp, plancher3[u]) for j in range(1, PARTS + 1)]
             for u in sorties}
    n3_base = _partager(sorties, cout3)
    if n3_base is None:
        raise Refus('Aucune taille d’examen ne livre un modèle au niveau visé avec la puissance de la méthode.')

    cache = {}

    def filtre(u, n3):
        """Coût du filtre de la sortie u pour chaque part j de la cible, l'examen de u ayant n3 données."""
        if (u, n3) not in cache:
            t = {c['id']: max(k3(c, n3, lot, marge_seuil) / n3 for lot in LOTS_LIVRAISON) for c in cu[u]}
            if any(t[c['id']] >= c['vise'] for c in cu[u]):
                cache[(u, n3)] = [None] * (PARTS + 1)
            else:
                def passe(n, j):
                    # Jugé sur les tailles que les lots auront vraiment : la sélection éventuellement arrondie par la
                    # part de l'entraînement (selection_de) et l'examen blanc qui la dépasse d'une donnée (tailles_de) ;
                    # la chance d'un seuil à fraction fixe n'est pas monotone en n (les ratés permis montent par paliers).
                    sel = selection_de(n)
                    for nl in (sel, max(n, sel + 1)):
                        s = 0.0
                        for c in cu[u]:
                            k = _k_filtre(t[c['id']], nl)
                            if _chance(nl, c['barre'], k) > cap:
                                return False
                            s += log_ch(nl, c['vise'], k)
                        if s < j / PARTS * lf:
                            return False
                    return True
                cache[(u, n3)] = [None] + [st.plus_petit_n(lambda n, j=j: passe(n, j), 1) for j in range(1, PARTS + 1)]
        return cache[(u, n3)]

    def essai(n3):
        nf = _partager(sorties, {u: filtre(u, n3[u]) for u in sorties})
        if nf is None:
            return None
        d = {lot: {u: (n3[u] if lot in LOTS_LIVRAISON else nf[u]) for u in sorties} for lot in LOTS_CALCUL}
        n = tailles_de(d)
        return sum(sum(n[lot].values()) for lot in ('entrainement', 'pre_evaluation') + LOTS_LIVRAISON), d

    echelles = (1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3)
    # Descente coordonnée : chaque groupe de sorties à son tour, les autres fixées ; les sorties aux mêmes critères
    # (mêmes barres, niveaux visés, planchers) bougent ensemble et gardent la même taille.
    groupes = {}
    for u in sorties:
        groupes.setdefault((plancher3[u], tuple((c['genre'], c['barre'], c['vise'], marge_du_critere(marge_dim, c), marge_du_critere(marge_seuil, c))
                                                for c in cu[u])), []).append(u)
    for g in groupes.values():   # le partage peut départager deux sorties identiques : elles prennent la plus grande taille
        for u in g:
            n3_base[u] = max(n3_base[v] for v in g)
    courant = dict(n3_base)
    r = essai(courant)
    for _ in range(2):
        for g in groupes.values():
            for e in echelles:
                x = {**courant, **{u: math.ceil(n3_base[u] * e) for u in g}}
                rx = essai(x)
                if rx is not None and (r is None or rx[0] < r[0]):
                    courant, r = x, rx
    if r is None:
        raise Refus('Aucune taille de sélection et d’examen blanc ne rend les filtres fiables au niveau visé.')
    d = r[1]
    fixe = {lot: {u: ('livraison au niveau visé (puissance partagée)' if lot in LOTS_LIVRAISON else 'filtre fiable au niveau visé')
                  for u in sorties} for lot in LOTS_CALCUL}
    for lot in LOTS_LIVRAISON:
        for u in sorties:
            if d[lot][u] == dem[lot][u]:
                fixe[lot][u] = fixe_plancher[lot][u]   # le plancher d'un test à la façon choisie suffit
    return d, fixe, n3_base


def _dimensionner_facon(st, m, *, facon, criteres, sorties, unites, regle_rares, alphas, puissance, marge_dim, marge_seuil, toutes_au_vise=False, filtres=None, n_impose=None, entrainement_min=None):
    """Le cœur du calcul E2.14 pour une façon (prudent | juste) : tailles par lot et par sortie, seuils de chaque porte
    critère par critère, courbe de la chance d'être reçu.

    1. Plancher de chaque critère, lot par lot, à la façon choisie : la barre (plus la marge des corrigés à l'examen et
       à la vérification) séparée du niveau visé avec la puissance de la méthode.
    2. Taille d'un lot par sortie = la plus grande demandée par les critères que la sortie porte.
    3. La livraison exige toutes les portes : la chance d'être reçu est le produit des chances de chaque test (trois
       portes, chaque critère, chaque lot), rendue pour la courbe et les profils. Elle n'est pas imposée par défaut :
       avec la puissance de la méthode par test, un modèle au niveau visé de chaque critère ne les franchit pas toutes
       8 fois sur 10. L'option du registre calcul.toutes_portes_au_vise (vrai) l'impose (voir plus bas).
    4. Option du registre calcul.portes_filtres (vrai), `filtres` = {chance_vise, chance_barre} : les portes 1 et 2
       deviennent des filtres avant l'examen (voir _tailles_filtres) ; la livraison (porte 3) garde seule la garantie,
       et un modèle au niveau visé de chaque critère est livré avec la puissance de la méthode.
    5. `n_impose` (tailles par lot et par sortie déjà fixées, celles du plan scellé de l'étape 2) : on ne refait pas
       les tailles, on ne refait que les seuils et les chances, avec la marge des corrigés `marge_seuil` (la
       confirmation de l'étape 3, cmd_confirmer_portes).
    6. `entrainement_min` (registre lots.entrainement_min) : la taille de l'entraînement ne se
       déduit plus de la sélection. Le cours (l'entraînement hors sélection) vaut au moins cette valeur, à parts
       égales entre sorties ; la sélection garde la taille que ses critères (ou les filtres) demandent, sans l'arrondi
       par la part de l'entraînement ; l'entraînement = la sélection + le cours. Sans la clé : l'ancienne règle,
       entraînement = sélection / (f (1 − f)), la sélection en étant la part f (methode.selection_fraction)."""
    def plancher(c, lot):
        p0 = c['barre'] + (marge_du_critere(marge_dim, c) if lot in LOTS_LIVRAISON else 0)
        p1 = min(c['vise'], 0.999999)
        if p0 >= p1:
            raise Refus(f"{c['libelle']} : la barre ({p0:.2%} avec la marge des corrigés) atteint le niveau visé ({p1:.2%}) ; aucune taille ne les sépare.")
        if facon == 'prudent' and not c['exact']:
            return st.dimensionner(alphas[lot], puissance, round(p1 - p0, 10))
        return st.dimensionner_niveaux(alphas[lot], puissance, p0, p1)

    requis = {c['id']: {lot: plancher(c, lot) for lot in LOTS_CALCUL} for c in criteres}
    frequences = {k: v / unites for k, v in sorties.items()}
    f = m['selection_fraction']
    cours = cours_par_sortie(entrainement_min, sorties)

    def selection_de(nsel):
        """La taille que la sélection aura vraiment pour nsel demandées."""
        return nsel if cours is not None else math.ceil(math.ceil(nsel / (f * (1 - f))) * f)

    def entrainement_de(u, nsel):
        """La taille de l'entraînement de la sortie u (sélection comprise) pour une sélection de nsel données."""
        return nsel + cours[u] if cours is not None else math.ceil(nsel / (f * (1 - f)))

    def tailles_de(dem):
        n = {lot: dict(dem[lot]) for lot in LOTS_CALCUL}
        if regle_rares == 'frequence_reelle' and min(frequences.values()) > 0:
            # Fréquence réelle : le lot entier grandit jusqu'à ce que chaque sortie, à sa vraie fréquence, ait son n.
            for lot in LOTS_CALCUL:
                tot = max(math.ceil(n[lot][u] / frequences[u]) for u in sorties)
                n[lot] = {u: math.ceil(tot * frequences[u]) for u in sorties}
        # Sinon (sur-représenter la sortie rare) : chaque sortie reçoit son propre n, quelle que soit sa fréquence réelle.
        if cours is not None:
            n['entrainement'] = {u: entrainement_de(u, n['selection'][u]) for u in sorties}
        else:
            n['entrainement'] = {u: math.ceil(n['selection'][u] / (f * (1 - f))) for u in sorties}
            n['selection'] = {u: math.ceil(n['entrainement'][u] * f) for u in sorties}
        n['pre_evaluation'] = {u: max(n['pre_evaluation'][u], n['selection'][u] + 1) for u in sorties}
        return n

    def portes_de(n):
        portes = {}
        for c in criteres:
            N = {lot: n[lot][c['compte_sur']] for lot in LOTS_CALCUL}
            marge = marge_du_critere(marge_seuil, c)
            lots = {}
            for lot in LOTS_LIVRAISON:
                p = c['barre'] + marge
                lots[lot] = {'n': N[lot], 'k': st.critique(N[lot], p, alphas[lot]) if p < 1 else N[lot] + 1}
            predit = max(st.niveau_predit(N[lot], lots[lot]['k'], puissance) for lot in LOTS_LIVRAISON)
            if filtres:
                # Filtres (calcul.portes_filtres) : le seuil de la porte 3, même fraction, sur la sélection et l'examen
                # blanc ; ils ne prouvent rien au niveau prédit et ne garantissent pas la livraison.
                porte2 = porte1 = max(lots[lot]['k'] / lots[lot]['n'] for lot in LOTS_LIVRAISON)
                for lot in ('pre_evaluation', 'selection'):
                    lots[lot] = {'n': N[lot], 'k': _k_filtre(porte2, N[lot])}
            else:
                k2 = st.critique(N['pre_evaluation'], predit, alphas['pre_evaluation']) if predit <= 1 else N['pre_evaluation'] + 1
                porte2 = k2 / N['pre_evaluation'] if predit <= 1 else predit
                lots['pre_evaluation'] = {'n': N['pre_evaluation'], 'k': k2}
                # Porte 1 = porte 2 : la borne des corrigés est déjà dans la porte 3, dont les portes 2 et 1 héritent (la
                # compter encore ici la compterait deux fois). Note m8 : resultat.portes.1.note.
                porte1 = min(1.0, porte2)
                k1 = math.ceil(porte1 * N['selection'] - 1e-9) if porte2 <= 1 else N['selection'] + 1
                lots['selection'] = {'n': N['selection'], 'k': k1}
            mot = 'exécutions à tort' if c['genre'] == 'plafond' else 'ratés'
            for x in lots.values():
                x['rates_max'] = x['n'] - x['k']
                x['seuil'] = round(x['k'] / x['n'], 6) if x['k'] <= x['n'] else None
                x['texte'] = f"au plus {x['rates_max']} {mot} sur {x['n']}" if x['k'] <= x['n'] else f"impossible sur {x['n']} données"
            portes[c['id']] = {'libelle': c['libelle'], 'genre': c['genre'], 'compte_sur': c['compte_sur'], 'touche': c['touche'],
                               'barre': c['barre'], 'vise': c['vise'], 'barre_testee': round(c['barre'] + marge, 6), 'filtre': bool(filtres),
                               'plancher': requis[c['id']], 'niveau_predit': predit, 'porte1': porte1, 'porte2': porte2,
                               'porte3': {lot: lots[lot]['seuil'] for lot in LOTS_LIVRAISON}, 'lots': {lot: lots[lot] for lot in LOTS_CALCUL}}
        return portes

    def chances_au_vise(portes):
        return {(cid, lot): _chance(x['lots'][lot]['n'], x['vise'], x['lots'][lot]['k']) for cid, x in portes.items() for lot in LOTS_CALCUL}

    dem = {lot: {u: max([requis[c['id']][lot] for c in criteres if c['compte_sur'] == u] or [1]) for u in sorties} for lot in LOTS_CALCUL}
    fixe = {lot: {u: max((c for c in criteres if c['compte_sur'] == u), key=lambda c: requis[c['id']][lot])['id'] for u in sorties} for lot in LOTS_CALCUL}
    if toutes_au_vise and n_impose is None:
        # Option (registre calcul.toutes_portes_au_vise) : chaque test au niveau visé reçoit la même part de la
        # puissance, π = puissance^(1/nombre de tests), pour que le produit atteigne la puissance. Pour chaque sortie,
        # on essaie plusieurs tailles d'examen (un examen plus grand abaisse le niveau prédit, donc les portes 2 et 1),
        # on en déduit l'examen blanc puis la sélection juste nécessaires, et l'on garde la combinaison la moins chère.
        pi = puissance ** (1 / (len(criteres) * len(LOTS_CALCUL)))
        for u in sorties:
            cu = [c for c in criteres if c['compte_sur'] == u]
            def n_examen(c, lot):
                p0 = c['barre'] + marge_du_critere(marge_dim, c)
                return st.plus_petit_n(lambda k: st.queue(k, c['vise'], st.critique(k, p0, alphas[lot])) >= pi, 50)
            base = {lot: max([dem[lot][u]] + [n_examen(c, lot) for c in cu]) for lot in LOTS_LIVRAISON}
            meilleur = None
            for mult in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
                n3 = {lot: math.ceil(base[lot] * mult) for lot in LOTS_LIVRAISON}
                npre, nsel = dem['pre_evaluation'][u], dem['selection'][u]
                possible = True
                for c in cu:
                    marge = marge_du_critere(marge_seuil, c)
                    predit = max(st.niveau_predit(n3[l], st.critique(n3[l], c['barre'] + marge, alphas[l]), puissance) for l in LOTS_LIVRAISON)
                    if predit >= c['vise']:
                        possible = False
                        break
                    npre = max(npre, st.plus_petit_n(lambda k: st.queue(k, c['vise'], st.critique(k, predit, alphas['pre_evaluation'])) >= pi, 50))
                if not possible:
                    continue
                for c in cu:
                    marge = marge_du_critere(marge_seuil, c)
                    predit = max(st.niveau_predit(n3[l], st.critique(n3[l], c['barre'] + marge, alphas[l]), puissance) for l in LOTS_LIVRAISON)
                    p2 = st.critique(npre, predit, alphas['pre_evaluation']) / npre
                    if p2 >= c['vise']:
                        possible = False
                        break
                    nsel = max(nsel, st.plus_petit_n(lambda k: st.queue(k, c['vise'], math.ceil(p2 * k - 1e-9)) >= pi, 50))
                if not possible:
                    continue
                cout = sum(n3.values()) + max(npre, nsel + 1) + entrainement_de(u, nsel)
                if meilleur is None or cout < meilleur[0]:
                    meilleur = (cout, n3, npre, nsel)
            if meilleur is None:
                raise Refus(f'Sortie {u} : aucune taille ne fait franchir toutes les portes au niveau visé.')
            _, n3, npre, nsel = meilleur
            for lot, v in (*n3.items(), ('pre_evaluation', npre), ('selection', nsel)):
                if v > dem[lot][u]:
                    dem[lot][u], fixe[lot][u] = v, 'toutes les portes au niveau visé'
    examen_livraison_seule = None
    if n_impose is not None:
        # Confirmation de l'étape 3 : les tailles du plan scellé, telles quelles (le banc est fabriqué sur elles).
        dem = None
        n = {lot: {u: int(n_impose[lot][u]) for u in sorties} for lot in ('entrainement',) + LOTS_CALCUL}
        fixe = {lot: {u: 'plan scellé de l’étape 2' for u in sorties} for lot in LOTS_CALCUL}
    elif filtres:
        if toutes_au_vise:
            raise Refus('calcul.portes_filtres et calcul.toutes_portes_au_vise ne vont pas ensemble : choisir l’un des deux.')
        dem, fixe, examen_livraison_seule = _tailles_filtres(st, criteres=criteres, sorties=list(sorties), alphas=alphas, puissance=puissance,
                                     marge_dim=marge_dim, marge_seuil=marge_seuil, dem=dem, fixe_plancher=fixe, filtres=filtres,
                                     tailles_de=tailles_de, selection_de=selection_de)
    if n_impose is None:
        n = tailles_de(dem)
    portes = portes_de(n)
    ch = chances_au_vise(portes)
    tailles = {lot: sum(n[lot].values()) for lot in ('entrainement',) + LOTS_CALCUL}
    d = {'n': n, 'fixe': fixe, 'tailles': tailles, 'frequences': frequences, 'criteres': criteres, 'portes_par_critere': portes,
         'cours': {u: n['entrainement'][u] - n['selection'][u] for u in sorties}, 'entrainement_min': entrainement_min,
         'chance_au_vise': math.prod(ch.values()),
         # Option filtres : l'examen (par sortie) qui livrerait un modèle au niveau visé avec la puissance juste, avant
         # qu'un examen plus grand ne soit gardé parce qu'il rend les filtres moins chers.
         'examen_livraison_seule': examen_livraison_seule if filtres else None,
         'chance_livraison_au_vise': math.prod(v for (cid, lot), v in ch.items() if lot in LOTS_LIVRAISON),
         'chance_filtres_au_vise': {lot: math.prod(v for (cid, l), v in ch.items() if l == lot) for lot in ('selection', 'pre_evaluation')},
         # Chance qu'un modèle à la barre d'un critère franchisse le test de ce critère, lot par lot (filtres : au plus
         # filtres.chance_barre ; livraison : au plus le risque du lot).
         'chance_a_la_barre': {cid: {lot: round(_chance(x['lots'][lot]['n'], x['barre'], x['lots'][lot]['k']), 6) for lot in LOTS_CALCUL}
                               for cid, x in portes.items()}}
    # Courbe : chaque sortie à δ points au-dessus de SA barre (B1 suit la sortie porteuse), l'exécution à tort à son
    # niveau visé ; la chance de franchir les trois portes, tous critères, tous lots, et celle de la livraison seule.
    courbe = []
    for i in range(0, 11):
        dl = i / 100
        profil = {'sorties': {c['compte_sur']: min(1.0, round(c['barre'] + dl, 6)) for c in criteres if c['genre'] == 'justesse'}}
        b1 = next((c for c in criteres if c['genre'] == 'b1'), None)
        if b1:
            profil['b1'] = min(1.0, round(b1['barre'] + dl, 6))
        courbe.append({'decalage': dl, 'sorties': profil['sorties'], 'chance': chance_profil(d, profil)[0],
                       'chance_livraison': chance_profil(d, profil, LOTS_LIVRAISON)[0]})
    d['courbe'] = courbe
    return d


def cours_par_sortie(entrainement_min, sorties):
    """Le cours minimum de chaque sortie (registre lots.entrainement_min) : la valeur répartie à
    parts égales entre les sorties, arrondie au-dessus (la somme vaut au moins le minimum) ; None sans la clé."""
    if entrainement_min is None:
        return None
    return {u: math.ceil(int(entrainement_min) / len(sorties)) for u in sorties}


def profils_defaut(criteres):
    """Profils lus par défaut : au niveau visé de chaque critère, et à la barre de chaque critère."""
    js = [c for c in criteres if c['genre'] == 'justesse']
    pl = [c for c in criteres if c['genre'] == 'plafond']
    vise = {'nom': 'au niveau visé', 'sorties': {c['compte_sur']: c['vise'] for c in js}}
    barre = {'nom': 'à la barre', 'sorties': {c['compte_sur']: c['barre'] for c in js}}
    if pl:
        vise['executer_a_tort'] = pl[0]['taux_vise']
        barre['executer_a_tort'] = pl[0]['taux_barre']
    return [vise, barre]


def _contexte_calcul(reg, pilote, m):
    """Ce que le calcul lit du registre, de la méthode et des mesures du pilote, de la même façon à l'étape 2 (cmd_calcul)
    et à la confirmation de l'étape 3 (cmd_confirmer_portes, sur le registre et la méthode gardés avec le calcul)."""
    facon = valeur(reg, 'calcul.facon', 'prudent')
    if facon not in ('prudent', 'juste'):
        raise Refus('calcul.facon : prudent ou juste.')
    sorties = pilote.get('sorties') or {}
    unites = int(pilote.get('unites') or 0)
    if not sorties or unites <= 0 or sum(sorties.values()) > unites:
        raise Refus('Mesures du pilote incohérentes (sorties et unités).')
    risque, puissance = m['risque'], m['puissance']
    # Risque par lot . La livraison exige l'examen ET la vérification, et chaque critère sur chacun :
    # un modèle sous une barre n'est livré que s'il franchit TOUS ces tests ; la chance de livrer à tort est donc au
    # plus celle d'UN seul test (test d'intersection-union, Berger 1982 : aucun partage entre critères ni entre les
    # deux lots). Seules les tentatives d'examen s'additionnent (un modèle différent à chaque tentative, chacun pouvant
    # passer par chance) : risque / tentatives par lot. L'ancien risque / (2 × tentatives) partageait le risque
    # comme si UN des deux lots suffisait à livrer, ce qui n'est pas la règle des portes.
    alphas = {'selection': risque, 'pre_evaluation': risque / m['consultations'],
              'examen': risque / m['tentatives_examen'], 'verification': risque / m['tentatives_examen']}
    toutes_au_vise = bool(valeur(reg, 'calcul.toutes_portes_au_vise', False, obligatoire=False))
    # Option calcul.portes_filtres : portes 1 et 2 = filtres au seuil de
    # la porte 3, la livraison seule garantit ; n'impose rien aux chantiers qui ne la posent pas.
    portes_filtres = bool(valeur(reg, 'calcul.portes_filtres', False, obligatoire=False))
    filtres = {'chance_vise': float(m['filtre_chance_vise']), 'chance_barre': float(m['filtre_chance_barre'])} if portes_filtres else None
    if filtres and not (0 < filtres['chance_vise'] < 1 and 0 < filtres['chance_barre'] < 1):
        raise Refus('calcul.filtre_chance_vise et calcul.filtre_chance_barre : entre 0 et 1.')
    # L'entraînement ne se déduit plus de la sélection quand le
    # registre fixe son minimum hors sélection (lots.entrainement_min) ; sans la clé, l'ancienne règle.
    ent_min = valeur(reg, 'lots.entrainement_min', None, obligatoire=False)
    if ent_min is not None:
        if isinstance(ent_min, bool) or not isinstance(ent_min, (int, float)) or ent_min < 0 or int(ent_min) != ent_min:
            raise Refus('lots.entrainement_min : un nombre entier de données, au moins 0 (le cours, hors sélection).')
        ent_min = int(ent_min)
    return {'facon': facon, 'sorties': sorties, 'unites': unites, 'criteres': criteres_portes(reg, list(sorties)),
            'regle_rares': valeur(reg, 'cas_rares.regle', 'sur_representer'),
            'minimum_cas': valeur(reg, 'cas_rares.minimum', 0, obligatoire=False) or 0,
            'risque': risque, 'puissance': puissance, 'alphas': alphas,
            'toutes_au_vise': toutes_au_vise, 'portes_filtres': portes_filtres, 'filtres': filtres, 'entrainement_min': ent_min}


REGLE_BORNE_PREVUE = (
    "À l'étape 2, la vérité des étiquettes n'est mesurée que sur le pilote ; les relectures de fiabilité se font pendant "
    "la fabrication (étape 3). Quand le pilote a moins de relectures que le plan n'en demande (N = le plus petit nombre "
    "de relectures qui, sans erreur, donne une borne exacte au plus égale à etiquettes.tolerance, même risque) et que ses "
    "erreurs ne réfutent pas la tolérance (test binomial exact au risque de la méthode), sa borne ne dit rien de la "
    "tolérance : les tailles ET les seuils se posent avec la borne prévue (la tolérance), à confirmer. "
    "Le plan de l'étape 3 compte les relectures pour etiquettes.erreurs_permises erreurs (0 par défaut : N). "
    "À l'étape 3, l'outil confirmer_portes lit la décision sur les relectures du plan, les premières du banc : borne mesurée au plus "
    "égale à la tolérance → le calcul se relance sur les tailles scellées avec la borne mesurée et les portes se figent ; "
    "plus d'erreurs que le plan n'en permet sur ces relectures → l'écart ferme la fabrication (aucune dépense, pas de "
    "scellement de l'étape 3) jusqu'à la réouverture de l'étape 2 (nouvelle tolérance, nouveau calcul).")

REGLE_PLAN_PAR_SORTIE = (
    "Clé etiquettes.plan_par_sortie à true : la borne des corrigés "
    "s'ajoute à la barre de CHAQUE sortie, et seulement aux lots du test (examen blanc, examen, vérification) ; le plan la "
    "prouve donc là où les portes la lisent. PAR SORTIE, N relectures (N = le plan pour etiquettes.tolerance avec "
    "etiquettes.erreurs_permises erreurs) tirées au hasard, graine fixée avant, dans les données gardées du TEST de cette "
    "sortie (la sortie du corrigé) ; règle par sortie : au plus etiquettes.erreurs_permises erreurs sur ses N. "
    "confirmer_portes lit, pour chaque sortie, les N premières relectures des données du test proposées avec cette "
    "sortie (etape3/a-relire.jsonl, champs reponse et lot ; les relectures hors du test ne comptent pas) ; la borne "
    "mesurée d'une sortie s'applique aux critères qui comptent sur elle (sa justesse, B1 pour EXÉCUTER), jamais une borne "
    "commune. Une sortie au-delà de sa règle ferme la fabrication dès que l'erreur de trop est notée. Le plan compte "
    "N × (nombre de sorties) relectures. Sans la clé (défaut false) : un seul plan de N relectures, comme avant.")


REGLE_INVERSIONS_EXECUTER = (
    "Clé plafond.executer_a_tort.borne_corriges à false : le plafond d'exécution "
    "à tort est testé sans la borne des corrigés. Le risque que cette borne couvrait (un corrigé EXÉCUTER dont la bonne "
    "sortie est SUGGÉRER ou NE RIEN FAIRE cache une exécution à tort que les strates du plafond ne comptent pas) est couvert par la relecture de fiabilité : parmi les relectures du plan (les premières du banc, autant "
    "que etiquettes.plan.relectures), confirmer_portes compte À PART les inversions vers EXÉCUTER (donnée proposée avec la "
    "réponse EXECUTER, corrigée vers une strate du plafond). Règle écrite avant les relectures, au calcul de l'étape 2 : "
    "elles ne doivent pas dépasser le plus grand nombre qui garde une borne exacte (Clopper-Pearson unilatérale, risque de "
    "la méthode) au plus égale à (barre du plafond − visé) / 2 sur ces relectures ; au-delà, dès qu'elles sont trouvées, "
    "l'écart ferme la fabrication comme une borne des étiquettes dépassée (réouverture de l'étape 2). "
    "Exemple chiffré (2 % / 0,5 %, 473 relectures, risque 5 %) : tolérance 0,75 %, 0 inversion admise (0 → borne 0,63 % ; "
    "1 → 1,00 %).")


REGLE_INVERSIONS_PAR_SORTIE = (
    "Plan par sortie (etiquettes.plan_par_sortie) : les inversions vers EXÉCUTER se comptent sur "
    "les N relectures des corrigés EXÉCUTER du test, et la règle se dit dans l'unité des strates du plafond (le constat 2 "
    "de l'audit : une part des relectures n'est pas une part des strates). Une part p de corrigés EXÉCUTER inversés cache "
    "p × n(EXÉCUTER) exécutions à tort, rapportées aux données des strates, Σ n(strate) : il faut p × n(EXÉCUTER) / "
    "Σ n(strate) ≤ (barre − visé) / 2 du plafond, à l'examen et à la vérification (le lot le plus strict). La borne des "
    "corrigés EXÉCUTER admise vaut donc (barre − visé) / 2 × min Σ n(strate) / n(EXÉCUTER), et le nombre admis est le plus "
    "grand qui la garde sur les N relectures. Limite écrite : si toutes les inversions cachées tombent dans UNE strate, "
    "elles y pèsent Σ n(strate) / n(strate) fois plus (champ points_une_strate).")


def regle_inversions_executer(st, criteres, plan, risque, n_par_sortie=None):
    """La règle des inversions vers EXÉCUTER (REGLE_INVERSIONS_EXECUTER), fixée au calcul de l'étape 2 ; None quand le
    plafond garde la borne des corrigés (ou qu'il n'y a pas de plafond). Plan par sortie (`plan['par_sortie']`, tailles
    `n_par_sortie` du calcul) : REGLE_INVERSIONS_PAR_SORTIE."""
    pl = [c for c in criteres if c['genre'] == 'plafond' and not c.get('borne_corriges', True)]
    if not pl:
        return None
    if not plan:
        raise Refus("plafond.executer_a_tort.borne_corriges à false : il faut la relecture de fiabilité qui compte les "
                    "inversions vers EXÉCUTER, donc une tolérance des étiquettes (etiquettes.tolerance).")
    tol = round((pl[0]['taux_barre'] - pl[0]['taux_vise']) / 2, 10)
    strates = [c['compte_sur'] for c in pl]
    n = int(plan['relectures'])
    par_sortie = bool(plan.get('par_sortie'))
    tol_relues, unite = tol, None
    if par_sortie:
        if 'EXECUTER' not in (n_par_sortie or {}).get('examen', {}):
            raise Refus("etiquettes.plan_par_sortie : les inversions vers EXÉCUTER se comptent sur les corrigés EXÉCUTER du test ; "
                        "il faut une sortie EXECUTER.")
        rapports = {l: sum(n_par_sortie[l][s] for s in strates) / n_par_sortie[l]['EXECUTER'] for l in LOTS_LIVRAISON}
        lot = min(rapports, key=rapports.get)
        tol_relues = round(tol * rapports[lot], 10)
        unite = {'lot': lot, 'executer': n_par_sortie[lot]['EXECUTER'], 'strates': {s: n_par_sortie[lot][s] for s in strates},
                 'tolerance_strates': tol, 'tolerance_corriges_executer': tol_relues}
    permises = st.erreurs_permises(tol_relues, risque, n)
    if permises < 0:
        raise Refus(f"plafond.executer_a_tort.borne_corriges à false : sur les {n} relectures du plan, même zéro inversion vers "
                    f"EXÉCUTER ne donne pas une borne exacte ≤ {tol_relues:.2%} ((barre − visé) / 2 du plafond"
                    f"{', ramené aux corrigés EXÉCUTER du test' if par_sortie else ''}) ; il en faut au moins "
                    f"{st.relectures_necessaires(tol_relues, risque)} (augmenter etiquettes.erreurs_permises, ou garder la borne des corrigés).")
    a_zero = st.borne_erreur(erreurs=0, relues=n, risque=risque)
    x = {'tolerance': tol_relues, 'relectures': n, 'permises': permises, 'strates': strates,
         'borne_a_zero': a_zero, 'borne_au_dela': st.borne_erreur(erreurs=permises + 1, relues=n, risque=risque),
         'texte': (f"au plus {permises} inversion{'s' if permises > 1 else ''} vers EXÉCUTER sur les {n} relectures "
                   + (f"des corrigés EXÉCUTER du test (borne exacte ≤ {tol_relues:.2%} des corrigés EXÉCUTER, soit ≤ {tol:.2%} "
                      f"des strates du plafond = (barre − visé) / 2)" if par_sortie else
                      f"du plan (borne exacte ≤ {tol:.2%} = (barre − visé) / 2 du plafond)")
                   + " ; au-delà, la fabrication se ferme"),
         'regle': REGLE_INVERSIONS_EXECUTER + (' ' + REGLE_INVERSIONS_PAR_SORTIE if par_sortie else '')}
    if par_sortie:
        # Ce que borne la règle quand elle tient (le nombre admis trouvé) : exécutions à tort cachées au plus, et leur
        # poids sur les deux strates réunies et sur une seule (limite écrite).
        b = st.borne_erreur(erreurs=permises, relues=n, risque=risque)
        cachees = b * unite['executer']
        unite.update(borne_corriges_executer=b, cachees_au_plus=round(cachees, 2),
                     points_strates=round(cachees / sum(unite['strates'].values()), 6),
                     points_une_strate=round(cachees / min(unite['strates'].values()), 6))
        x['unite'] = unite
    return x


def borne_des_corriges(st, verite, tolerance, risque, erreurs_plan=0, sorties_plan=None):
    """La marge des corrigés du calcul  et le plan de relecture qui la confirme.

    La note mesurée contre les corrigés s'écarte de la vraie justesse d'au plus la part de corrigés faux ; pour prouver
    « vraie justesse ≥ barre », l'examen et la vérification testent la barre + la borne. Les tailles sont faites pour la
    tolérance choisie (la borne que les relectures doivent atteindre) ; les seuils lisent la borne mesurée, SAUF quand
    elle vient d'un pilote trop petit pour rien dire de la tolérance (moins de relectures que le plan sans erreur) : les
    seuils prennent alors la borne prévue, à confirmer à l'étape 3 (REGLE_BORNE_PREVUE, cmd_confirmer_portes). Le
    plafond la reçoit aussi : un corrigé EXÉCUTER qui serait vraiment NE RIEN FAIRE cache une
    exécution à tort que ses strates ne comptent pas, et la tolérance des étiquettes en admet.
    `erreurs_plan` (registre etiquettes.erreurs_permises, 0 par défaut) : les erreurs que le plan de relecture de
    l'étape 3 admet ; le plan compte alors plus de relectures (1 % au risque 5 % : 299 sans erreur, 473 pour une).
    `sorties_plan` (registre etiquettes.plan_par_sortie, REGLE_PLAN_PAR_SORTIE) : le plan compte ses relectures PAR
    SORTIE, dans le test seulement ; plan['relectures'] est alors le nombre d'une sortie."""
    relues = int(verite.get('relues', 0) or 0) if verite else 0
    erreurs = int(verite.get('erreurs', 0) or 0) if verite else 0
    mesuree = st.borne_erreur(erreurs=erreurs, relues=max(relues, 1), risque=risque) if verite else None
    tol = float(tolerance) if tolerance is not None else None
    plan = None
    if tol is not None:
        e_plan = int(erreurs_plan or 0)
        plan = {'relectures_sans_erreur': st.relectures_necessaires(tol, risque),
                'relectures_selon_erreurs': {str(e): st.relectures_necessaires(tol, risque, e) for e in sorted({0, 1, 2, e_plan})},
                'erreurs_permises': e_plan, 'relectures': st.relectures_necessaires(tol, risque, e_plan)}
        if sorties_plan:
            plan.update(par_sortie=True, sorties=list(sorties_plan), lots=list(LOTS_TEST),
                        relectures_total=plan['relectures'] * len(sorties_plan), regle=REGLE_PLAN_PAR_SORTIE)
    # Le pilote contredit-il déjà la tolérance ? Test binomial exact au risque de la méthode : avec un taux d'erreur égal
    # à la tolérance, trouver au moins autant d'erreurs serait si rare (≤ risque) que la tolérance est réfutée ; la
    # borne mesurée garde alors les seuils et le motif de compromis reste (ce n'est plus un échantillon trop petit).
    contredit = bool(tol is not None and erreurs > 0 and relues and st.queue(relues, tol, erreurs) <= risque)
    # Plan par sortie : les relectures du pilote ne sont ni par sortie ni dans le test ; elles ne confirment jamais la
    # borne que les portes lisent (REGLE_PLAN_PAR_SORTIE).
    a_confirmer = plan is not None and (bool(sorties_plan) or relues < plan['relectures_sans_erreur']) and not contredit
    dimension = tol if tol is not None else (mesuree or 0.0)
    seuils = tol if a_confirmer else (mesuree if mesuree is not None else dimension)
    motif = None
    if a_confirmer:
        n, e_plan = plan['relectures'], plan['erreurs_permises']
        quoi = (f"{n} relectures par sortie dans le test ({n * len(sorties_plan)} en tout)" if sorties_plan else f"{n} relectures")
        motif = (f"à confirmer par {quoi} à l'étape 3 : le pilote n'en a que {relues} ({erreurs} erreur"
                 f"{'s' if erreurs > 1 else ''}, borne mesurée {mesuree:.1%})" if mesuree is not None else
                 f"à confirmer par {quoi} à l'étape 3 : le pilote n'a pas de relecture")
        motif += ((f", trop peu pour rien dire de la tolérance ({tol:.1%})" if relues < plan['relectures_sans_erreur'] else
                   ", ni par sortie ni dans le test") + " ; les portes sont posées avec la borne prévue "
                  + (f"({tol:.1%}) et se figent à l'étape 3 sur la borne mesurée par ces {n} relectures " if not sorties_plan else
                     f"({tol:.1%}) et se figent à l'étape 3, chaque sortie sur la borne mesurée par ses {n} relectures ")
                  + ("(sans erreur), ou la fabrication se ferme si elles en trouvent" if e_plan == 0 else
                     f"(au plus {e_plan} erreur{'s' if e_plan > 1 else ''}{' par sortie' if sorties_plan else ''}), ou la fabrication se ferme si elles en trouvent plus"))
    return {'dimension': dimension, 'seuils': seuils, 'borne_mesuree': mesuree, 'tolerance': tol, 'borne_prevue': tol,
            'relues_pilote': relues if verite else None, 'erreurs_pilote': erreurs if verite else None,
            'plan': plan, 'a_confirmer': a_confirmer, 'pilote_contredit_tolerance': contredit, 'motif': motif, 'regle': REGLE_BORNE_PREVUE if plan else None}


def cmd_calcul(ch, a):
    """E2.14 : le programme calcule les tailles des lots (par lot et par sortie), les seuils de chaque porte critère par
    critère, le minimum par sortie et la chance d'être reçu, à partir des choix de l'utilisateur (registre) et des
    mesures du pilote. Paramètre facultatif `profils` : [{nom, sorties: {sortie: justesse}, executer_a_tort, b1}],
    lus par le programme (chance de franchir chaque porte), pour qu'aucun agent ne la calcule lui-même."""
    import statistiques as st
    with ch.verrou():
        c = ch.lire()
        if c['etapes']['2']['etat'] not in ('ouverte',):
            raise Refus("Le calcul se fait pendant l'étape 2 ouverte.")
        reg = charger_json(ch.chemin('registre.json'), {})
        pilote = charger_json(ch.chemin('etape2', 'pilote', 'mesures.json'))
        if not pilote:
            raise Refus("Les mesures du pilote manquent (etape2/pilote/mesures.json : unites, sorties {nom: compte}, verite {relues, erreurs}, voie).")
        m = methode(reg)
        x = _contexte_calcul(reg, pilote, m)
        facon, sorties, unites, criteres, regle_rares = x['facon'], x['sorties'], x['unites'], x['criteres'], x['regle_rares']
        minimum_cas, risque, puissance, alphas = x['minimum_cas'], x['risque'], x['puissance'], x['alphas']
        toutes_au_vise, portes_filtres, filtres = x['toutes_au_vise'], x['portes_filtres'], x['filtres']
        ent_min = x['entrainement_min']
        tolerance = valeur(reg, 'etiquettes.tolerance', None, obligatoire=False)
        # etiquettes.plan_par_sortie, REGLE_PLAN_PAR_SORTIE.
        par_sortie = valeur(reg, 'etiquettes.plan_par_sortie', False, obligatoire=False)
        if not isinstance(par_sortie, bool):
            raise Refus('etiquettes.plan_par_sortie : true ou false.')
        if par_sortie and tolerance is None:
            raise Refus("etiquettes.plan_par_sortie : il faut une tolérance des étiquettes (etiquettes.tolerance).")
        b = borne_des_corriges(st, pilote.get('verite') or {}, tolerance, risque,
                               valeur(reg, 'etiquettes.erreurs_permises', 0, obligatoire=False),
                               sorties_plan=list(sorties) if par_sortie else None)
        borne, marge_dim, marge_seuil = b['borne_mesuree'], b['dimension'], b['seuils']
        # Sans plan par sortie, la règle des inversions ne dépend que du plan : elle refuse avant le dimensionnement ;
        # avec lui, elle se dit dans l'unité des strates, donc sur les tailles calculées (plus bas).
        inversions = None if par_sortie else regle_inversions_executer(st, criteres, b['plan'], risque)

        def dim(fac):
            return _dimensionner_facon(st, m, facon=fac, criteres=criteres, sorties=sorties, unites=unites, regle_rares=regle_rares,
                                       alphas=alphas, puissance=puissance, marge_dim=marge_dim, marge_seuil=marge_seuil,
                                       toutes_au_vise=toutes_au_vise, filtres=filtres, entrainement_min=ent_min)

        d = dim(facon)
        n, tailles, portes = d['n'], d['tailles'], d['portes_par_critere']
        if par_sortie:
            inversions = regle_inversions_executer(st, criteres, b['plan'], risque, n_par_sortie=n)
        usages = ('entrainement', 'pre_evaluation', 'examen', 'verification')
        total = sum(tailles[u] for u in usages)
        profils = profils_defaut(criteres) + list(a.get('profils') or [])
        lecture_profils = []
        for p in profils:
            if set(p.get('sorties') or {}) != set(sorties):
                raise Refus(f"Profil « {p.get('nom')} » : donner la justesse de chaque sortie ({', '.join(sorties)}).")
            tout, detail = chance_profil(d, p)
            livr, detail_l = chance_profil(d, p, LOTS_LIVRAISON)
            lecture_profils.append({**p, 'chance_recu': tout, 'chance_livraison': livr, 'par_critere': detail, 'par_critere_livraison': detail_l,
                                    'chance_filtre1': chance_profil(d, p, ('selection',))[0], 'chance_filtre2': chance_profil(d, p, ('pre_evaluation',))[0]})
        # E2.10 : les deux façons côte à
        # côte, une ligne par porte (critère), sur l'examen et la vérification réunis, en conséquences chiffrées par le
        # programme, pour que l'agent montre un tableau de chiffres, jamais son propre calcul.
        comparaison = {}
        for fac in ('prudent', 'juste'):
            e = d if fac == facon else dim(fac)
            lignes = []
            for cid, x in e['portes_par_critere'].items():
                cr = next(c for c in criteres if c['id'] == cid)
                def livre(q):
                    return math.prod(_chance(x['lots'][l]['n'], q, x['lots'][l]['k']) for l in LOTS_LIVRAISON)
                lignes.append({'critere': cid, 'libelle': x['libelle'], 'barre': x['barre'], 'vise': x['vise'],
                               'examen': x['lots']['examen']['texte'], 'verification': x['lots']['verification']['texte'],
                               'seuil_examen': x['porte3']['examen'],
                               'livrer_a_la_barre': round(livre(cr['barre']), 6),
                               'refus_au_vise': round(1 - livre(cr['vise']), 4),
                               'refus_toutes_portes_au_vise': round(1 - math.prod(_chance(x['lots'][l]['n'], cr['vise'], x['lots'][l]['k']) for l in LOTS_CALCUL), 4)})
            vise = profils_defaut(criteres)[0]
            comparaison[fac] = {
                'total': sum(e['tailles'][u] for u in usages), 'tailles': e['tailles'], 'par_sortie': e['n'],
                'risque_livrer_sous_barre': risque, 'portes': lignes,
                'chance_livraison_au_vise': chance_profil(e, vise, LOTS_LIVRAISON)[0],
                'chance_toutes_portes_au_vise': chance_profil(e, vise)[0],
                'chance_filtres_au_vise': {l: round(v, 4) for l, v in e['chance_filtres_au_vise'].items()},
                'refus_par_malchance': [{'decalage': p['decalage'], 'livraison': round(1 - p['chance_livraison'], 4),
                                         'toutes_portes': round(1 - p['chance'], 4)} for p in e['courbe']]}
        minimum_par_sortie = {u: max(minimum_cas, sum(n[l][u] for l in usages)) for u in sorties}
        motifs = []
        if borne is not None and tolerance is not None and borne > float(tolerance) and not b['a_confirmer']:
            motifs.append(f'la borne d’erreur des étiquettes ({borne:.3%}) dépasse la tolérance choisie ({float(tolerance):.1%})')
        for cid, x in portes.items():
            if borne is not None and not filtres and x['genre'] != 'plafond' and x['porte1'] > 1 - marge_seuil:
                motifs.append(f"{x['libelle']} : la porte 1 est au-dessus de ce que les étiquettes permettent de prouver")
            imp = [l for l in LOTS_CALCUL if x['lots'][l]['k'] > x['lots'][l]['n']]
            if imp:
                motifs.append(f"{x['libelle']} : porte impossible sur {', '.join(imp)}")
        if filtres:
            if d['chance_livraison_au_vise'] < puissance:
                motifs.append(f"un modèle au niveau visé n'est livré que {d['chance_livraison_au_vise']:.1%} du temps (puissance de la méthode {puissance:.0%})")
            for lot, v in d['chance_filtres_au_vise'].items():
                if v < filtres['chance_vise']:
                    motifs.append(f"filtre {'1' if lot == 'selection' else '2'} : un modèle au niveau visé ne le franchit que {v:.1%} du temps (cible {filtres['chance_vise']:.0%})")
        elif d['chance_au_vise'] < puissance:
            motifs.append(f"un modèle au niveau visé de chaque critère ne franchit toutes les portes que {d['chance_au_vise']:.1%} du temps (puissance de la méthode {puissance:.0%}) ; calcul.toutes_portes_au_vise l'impose, à un autre volume")
        if pilote.get('voie') == 'collecte' and total > (pilote.get('inventaire') or float('inf')):
            motifs.append(f'{total} données nécessaires pour {pilote.get("inventaire")} disponibles à la récolte')
        # Valeurs du registre que ce calcul contredit : à mettre à jour avant le scellement.
        ecarts = []
        mps = valeur(reg, 'banc.min_par_sortie_test', None, obligatoire=False)
        # Le registre donne un minimum unique ou un minimum par sortie (un dict comparé à un
        # nombre listait un faux écart).
        if mps is not None and any(n['examen'][u] != (mps.get(u) if isinstance(mps, dict) else mps) for u in sorties):
            ecarts.append({'cle': 'banc.min_par_sortie_test', 'registre': mps, 'calcul': n['examen']})
        lt = valeur(reg, 'lots.tailles', None, obligatoire=False)
        if isinstance(lt, dict) and any(lt.get(l) not in (None, tailles[l]) for l in tailles):
            ecarts.append({'cle': 'lots.tailles', 'registre': lt, 'calcul': {**tailles, 'total': total}})
        def resume_fixe(lot):
            autres = [f'{u} : {cid}' for u, cid in d['fixe'][lot].items() if cid != f'justesse:{u}']
            return '; '.join(autres) if autres else 'la sortie (N1)'
        une = lambda cid, lot, cle: portes[cid]['lots'][lot][cle]
        resultat = {
            'a': maintenant(), 'facon': facon, 'methode': m, 'risque_par_lot': alphas,
            'criteres': [{k: v for k, v in c.items()} for c in criteres],
            'n_par_sortie': n, 'fixe_par_sortie': d['fixe'],
            'fixe_par': {'entrainement': (f"le cours (lots.entrainement_min : au moins {_nb(ent_min)} hors sélection, parts égales) + la sélection"
                                          if ent_min is not None else f"la sélection (part {m['selection_fraction']:g})".replace('.', ',')),
                         **{l: resume_fixe(l) for l in LOTS_CALCUL}},
            # L'entraînement = la sélection + le cours (hors sélection), ce dernier fixé par
            # lots.entrainement_min quand le registre le donne.
            'entrainement': {'minimum_hors_selection': ent_min, 'hors_selection': d['cours'],
                             'total_hors_selection': sum(d['cours'].values()), 'selection': n['selection'],
                             'regle': ('lots.entrainement_min : le cours vaut au moins cette valeur, à parts égales entre sorties ; '
                                       'la sélection garde la taille que ses critères demandent')
                                      if ent_min is not None else
                                      f"entraînement = sélection / (f (1 − f)), la sélection en étant la part f = {m['selection_fraction']:g}"},
            'tailles': tailles, 'total': total,
            'marge_corriges': {'dimension': marge_dim, 'seuils': marge_seuil, 'borne_mesuree': borne, 'tolerance': tolerance},
            # La vérité des étiquettes (REGLE_BORNE_PREVUE) : borne mesurée sur le pilote, borne prévue (la tolérance),
            # relectures sans erreur nécessaires (binomiale exacte) et, si le pilote est trop petit, le motif « à
            # confirmer par N relectures à l'étape 3 » ; ce motif n'est pas un compromis : il ne refuse rien.
            'etiquettes': {k: b[k] for k in ('borne_mesuree', 'borne_prevue', 'relues_pilote', 'erreurs_pilote', 'plan', 'a_confirmer',
                                             'pilote_contredit_tolerance', 'motif', 'regle')}
                          | {'inversions_vers_executer': inversions},
            'a_confirmer': ([b['motif']] if b['a_confirmer'] else []) + ([f"plafond sans la borne des corrigés : {inversions['texte']}"] if inversions else []),
            'portes_par_critere': portes, 'chance_au_vise': round(d['chance_au_vise'], 4), 'toutes_portes_au_vise': toutes_au_vise,
            'portes_filtres': portes_filtres, 'chance_livraison_au_vise': round(d['chance_livraison_au_vise'], 4),
            'filtres': {'cible_au_vise': filtres['chance_vise'], 'plafond_a_la_barre': filtres['chance_barre'],
                        'chance_au_vise': {l: round(v, 4) for l, v in d['chance_filtres_au_vise'].items()},
                        'examen_livraison_seule': d['examen_livraison_seule'],
                        'chance_a_la_barre': {cid: {l: v[l] for l in ('selection', 'pre_evaluation')} for cid, v in d['chance_a_la_barre'].items()},
                        'regle': NOTE_FILTRES} if filtres else None,
            'portes': {'1': {'borne_erreur_etiquettes': borne, 'borne_appliquee': marge_seuil, 'par_critere': {cid: x['porte1'] for cid, x in portes.items()},
                             'note': (NOTE_FILTRES if filtres else 'porte 1 = porte 2 : la borne des corrigés est dans la porte 3, dont les portes 2 et 1 '
                                      'héritent. Lue sur la sélection, consultée à chaque essai : le meilleur essai y est '
                                      'flatté par la sélection ; ce seuil, sans correction pour les '
                                      'consultations répétées, n\'est qu\'un filtre avant l\'examen blanc (un faux passage '
                                      'coûte une consultation, que la porte 2 compte dans son risque) : il ne garantit pas la livraison')},
                       '2': {'par_critere': {cid: x['porte2'] for cid, x in portes.items()}, 'niveau_predit': {cid: x['niveau_predit'] for cid, x in portes.items()},
                             'consultations': m['consultations'], **({'note': NOTE_FILTRES} if filtres else {})},
                       '3': {'par_critere': {cid: {l: une(cid, l, 'texte') for l in LOTS_LIVRAISON} for cid in portes},
                             'seuils': {cid: x['porte3'] for cid, x in portes.items()}, 'tentatives': m['tentatives_examen']}},
            'minimum_par_sortie': minimum_par_sortie, 'courbe_chance_recu': d['courbe'], 'profils': lecture_profils,
            'comparaison_facons': comparaison, 'frequences_pilote': d['frequences'],
            'motifs_compromis': motifs, 'ecarts_registre': ecarts, 'version_calcul': empreinte(os.path.join(ICI, 'statistiques.py')),
        }
        # les tableaux à montrer (tailles, seuils, chances, prudent / juste) sont écrits par le
        # programme, chiffres compris ; l'agent les recopie tels quels, il ne refait aucun calcul.
        resultat['tableaux'] = tableaux_calcul(resultat)
        ecrire_json(ch.chemin('etape2', 'calcul', 'parametres.json'), {'registre': {k: reg[k]['valeur'] for k in sorted(reg) if k.split('.')[0] in ('barre', 'niveau_vise', 'plafond', 'calcul', 'cas_rares', 'etiquettes', 'b1', 'banc') or k == 'lots.entrainement_min'}, 'pilote': pilote, 'methode': m, 'profils': a.get('profils') or []})
        ecrire_json(ch.chemin('etape2', 'calcul', 'resultat.json'), resultat)
        ch.journaliser('calcul_etape2', total=total, facon=facon, motifs=motifs)
        return resultat


def _nb(x):
    """Un nombre de données à la française : 14 396."""
    return f'{int(x):,}'.replace(',', '\u202f')


def _pc(x, chiffres=1):
    """Une chance en pour cent à la française : 99,9 % (0 % et 100 % sans décimale)."""
    if x is None:
        return '—'
    v = round(100 * x, chiffres)
    if v == 0 and x > 0:
        return f'< {10 ** -chiffres:g} %'.replace('.', ',')
    if v == 100 and x < 1:
        return f'> {100 - 10 ** -chiffres:g} %'.replace('.', ',')
    return (f'{v:.{chiffres}f}'.rstrip('0').rstrip('.') + ' %').replace('.', ',')


def _table(entete, lignes):
    out = ['| ' + ' | '.join(entete) + ' |', '|' + '|'.join('---' for _ in entete) + '|']
    out += ['| ' + ' | '.join(str(c) for c in l) + ' |' for l in lignes]
    return '\n'.join(out)


NOMS_LOTS = {'entrainement': 'Entraînement (sélection comprise)', 'selection': 'Sélection (filtre 1)',
             'pre_evaluation': 'Examen blanc (filtre 2)', 'examen': 'Examen', 'verification': 'Vérification'}


def tableaux_calcul(r):
    """Les tableaux du calcul de l'étape 2 en markdown, chiffres compris (« la comparaison
    prudent / juste et tous les chiffres sortent du programme ») : tailles par lot et par sortie, seuils de chaque
    porte, chances des profils, comparaison des deux façons. Rien n'y est recalculé : tout vient de `r`."""
    n = r['n_par_sortie']
    sorties = list(n['examen'])
    ent = r.get('entrainement') or {}
    lignes = []
    for lot in ('entrainement',) + LOTS_CALCUL:
        lignes.append([NOMS_LOTS[lot]] + [_nb(n[lot][u]) for u in sorties] + [_nb(r['tailles'][lot]), r['fixe_par'].get(lot, '')])
        if lot == 'entrainement' and ent.get('hors_selection'):
            lignes.append(['dont cours (hors sélection)'] + [_nb(ent['hors_selection'][u]) for u in sorties]
                          + [_nb(ent['total_hors_selection']), f"au moins {_nb(ent['minimum_hors_selection'])}"
                             if ent.get('minimum_hors_selection') is not None else ''])
            lignes.append(['dont sélection'] + [_nb(n['selection'][u]) for u in sorties] + [_nb(r['tailles']['selection']), ''])
    lignes.append(['Minimum par sortie'] + [_nb(r['minimum_par_sortie'][u]) for u in sorties] + [_nb(r['total']), 'total'])
    tailles = _table(['Lot'] + sorties + ['Total', 'Fixé par'], lignes)

    seuils = _table(['Porte (critère)', 'Barre testée', 'Sélection', 'Examen blanc', 'Examen', 'Vérification'],
                    [[x['libelle'], _pc(x['barre_testee'], 2)] + [x['lots'][l]['texte'] for l in LOTS_CALCUL]
                     for x in r['portes_par_critere'].values()])

    def tx(p):
        t = p.get('executer_a_tort')
        return '—' if t is None else ', '.join(f'{k} {_pc(v, 2)}' for k, v in t.items()) if isinstance(t, dict) else _pc(t, 2)
    profils = _table(['Profil'] + sorties + ['Exécution à tort', 'Livraison', 'Filtre 1', 'Filtre 2', 'Reçu de bout en bout'],
                     [[p['nom']] + [_pc(p['sorties'][u], 1) for u in sorties]
                      + [tx(p), _pc(p['chance_livraison']), _pc(p['chance_filtre1']), _pc(p['chance_filtre2']), _pc(p['chance_recu'])]
                      for p in r['profils']])

    cf = r.get('comparaison_facons') or {}
    facons = None
    if set(cf) >= {'prudent', 'juste'}:
        P, J = cf['prudent'], cf['juste']
        lignes = [['Données au total', _nb(P['total']), _nb(J['total'])]]
        for lot in ('entrainement',) + LOTS_CALCUL:
            lignes.append([NOMS_LOTS[lot], _nb(P['tailles'][lot]), _nb(J['tailles'][lot])])
        pj = {l['critere']: l for l in J['portes']}
        for l in P['portes']:
            j = pj[l['critere']]
            lignes.append([f"{l['libelle']} : seuil (examen, et de même à la vérification)", l['examen'], j['examen']])
            lignes.append([f"{l['libelle']} : livrer un modèle à la barre", _pc(l['livrer_a_la_barre'], 2), _pc(j['livrer_a_la_barre'], 2)])
            lignes.append([f"{l['libelle']} : refuser un modèle au niveau visé (malchance)", _pc(l['refus_au_vise']), _pc(j['refus_au_vise'])])
        lignes.append(['Livrer un modèle au niveau visé de chaque critère', _pc(P['chance_livraison_au_vise']), _pc(J['chance_livraison_au_vise'])])
        lignes.append(['Franchir toutes les portes au niveau visé', _pc(P['chance_toutes_portes_au_vise']), _pc(J['chance_toutes_portes_au_vise'])])
        facons = _table(['', 'Prudent', 'Au plus juste'], lignes)
    return {'tailles': tailles, 'seuils': seuils, 'profils': profils, 'facons': facons}


def lexique(ch):
    return lire_lignes(ch.chemin('etape2', 'lexique.jsonl'))


# ─── Étape 3 : la fabrication du banc (E3.1) et ta relecture (E3.2) ──────────────────────────────────────────────
# La chaîne de fabrication est conduite par le programme de la boucle ; elle écrit son état dans etape3/fabrication.json
# ({phases: [{nom, etat, comptes, cout_eur, duree_s}], devis_eur, arret}), que le module lit sans rien recalculer.


def vue_fabrication(ch):
    f = charger_json(ch.chemin('etape3', 'fabrication.json'))
    if not f:
        return None
    cout = sum((p.get('cout_eur') or 0) for p in f.get('phases', []))
    return dict(f, cout_eur=round(cout, 4), depasse=bool(f.get('devis_eur') is not None and cout > f['devis_eur']), fermee=fabrication_fermee(ch))


def relecture_etat(ch):
    import statistiques as st
    a_relire = lire_lignes(ch.chemin('etape3', 'a-relire.jsonl'))
    faites = {r['id']: r for r in lire_lignes(ch.chemin('etape3', 'relecture-utilisateur.jsonl'))}
    reg = charger_json(ch.chemin('registre.json'), {})
    tol = (reg.get('etiquettes.tolerance') or {}).get('valeur')
    risque = methode(reg)['risque']
    relues = len(faites)
    erreurs = sum(1 for r in faites.values() if r['verdict'] == 'corrige')
    borne = st.borne_erreur(erreurs=erreurs, relues=relues, risque=risque) if relues else None
    e = {'a_relire': len(a_relire), 'relues': relues, 'erreurs': erreurs, 'borne': borne, 'tolerance': tol,
         'depasse': bool(borne is not None and tol is not None and erreurs and borne > float(tol)),
         'restantes': [x['id'] for x in a_relire if x['id'] not in faites][:1]}
    plan = ((charger_json(ch.chemin('etape2', 'calcul', 'resultat.json')) or {}).get('etiquettes') or {}).get('plan') or {}
    if plan.get('par_sortie'):
        # REGLE_PLAN_PAR_SORTIE : la borne qui compte est celle de chaque sortie, dans le test (la borne d'ensemble
        # ci-dessus ne dit rien d'une sortie).
        par = {}
        for u in plan['sorties']:
            ids = [x['id'] for x in a_relire if x.get('lot') in LOTS_TEST and str(x.get('reponse') or '') == u]
            vues = [faites[i] for i in ids if i in faites]
            err = sum(1 for v in vues if v['verdict'] == 'corrige')
            b = st.borne_erreur(erreurs=err, relues=len(vues), risque=risque) if vues else None
            par[u] = {'a_relire': len(ids), 'relues': len(vues), 'erreurs': err, 'borne': b,
                      'depasse': bool(b is not None and tol is not None and err and b > float(tol))}
        e['par_sortie'] = par
        e['depasse'] = e['depasse'] or any(x['depasse'] for x in par.values())
    return e


def cmd_relire(ch, a):
    """E3.2 : la vue de relecture, une donnée à la fois avec sa bonne réponse ; valider ou corriger, laisser un mot.
    Pour les lots scellés, seule la vue du volet les lit : l'agent ne reçoit que les comptes (outil etat)."""
    action = a.get('action', 'suivante')
    with ch.verrou():
        a_relire = {x['id']: x for x in lire_lignes(ch.chemin('etape3', 'a-relire.jsonl'))}
        if action == 'suivante':
            e = relecture_etat(ch)
            if not e['restantes']:
                return {'donnee': None, 'etat': e}
            return {'donnee': a_relire[e['restantes'][0]], 'etat': e}
        if action == 'noter':
            did = a.get('id')
            if did not in a_relire:
                raise Refus(f'Donnée inconnue : {did}.')
            verdict = a.get('verdict')
            if verdict not in ('ok', 'corrige'):
                raise Refus('Verdict : ok ou corrige.')
            if verdict == 'corrige' and a.get('correction') in (None, ''):
                raise Refus('Une correction a besoin de la bonne réponse corrigée.')
            ajouter_ligne(ch.chemin('etape3', 'relecture-utilisateur.jsonl'),
                          {'a': maintenant(), 'id': did, 'verdict': verdict, 'correction': a.get('correction'), 'mot': a.get('mot'),
                           'lot': a_relire[did].get('lot')})
            ch.journaliser('relecture_utilisateur', verdict=verdict, lot=a_relire[did].get('lot'))
            return {'etat': relecture_etat(ch)}
        raise Refus('Action : suivante ou noter.')


def relectures_du_plan(ch):
    """Les relectures du banc dans leur ordre (etape3/relecture-utilisateur.jsonl), une par donnée, le PREMIER verdict
    comptant : une erreur trouvée ne s'efface pas en renotant la donnée."""
    vues, ordre = set(), []
    for r in lire_lignes(ch.chemin('etape3', 'relecture-utilisateur.jsonl')):
        if r.get('id') not in vues:
            vues.add(r.get('id'))
            ordre.append(r)
    return ordre


def confirmation_portes(ch):
    """L'état de la confirmation de l'étape 3 (etape3/confirmation-portes.json : figees | ecart), None sans elle."""
    return charger_json(ch.chemin('etape3', 'confirmation-portes.json'))


def fabrication_fermee(ch):
    """Le motif qui ferme la fabrication (écart à la borne prévue, REGLE_BORNE_PREVUE), None si elle est ouverte."""
    x = confirmation_portes(ch)
    return x['motif'] if x and x.get('etat') == 'ecart' else None


def cmd_confirmer_portes(ch, a):
    """E3 (REGLE_BORNE_PREVUE) : après les relectures de fiabilité, le calcul se relance avec la borne MESURÉE.

    • La décision se lit sur les N premières relectures du banc, N = relectures du plan (calcul scellé de l'étape 2,
      etiquettes.plan.relectures_sans_erreur) : un nombre fixé d'avance, pour que la borne exacte garde son risque
      (relire « jusqu'à ce que ça passe » le gonflerait).
    • Borne mesurée sur ces N relectures ≤ borne prévue (la tolérance) : on recalcule les seuils de chaque porte sur les
      tailles scellées (le banc est fabriqué sur elles) avec la borne mesurée, et les portes se FIGENT
      (etape3/confirmation-portes.json, état figees ; un nouvel appel rend ce fichier sans rien recalculer).
    • Plus d'erreurs que le plan n'en permet sur ces N relectures (dès qu'elles sont trouvées, même avant la N-ième) :
      l'ÉCART FERME LA FABRICATION (état ecart : plus de dépense, pas de scellement de l'étape 3) jusqu'à la réouverture
      de l'étape 2 (nouvelle tolérance, nouveau calcul), décision de l'utilisateur.
    • Plafond sans la borne des corrigés (clé plafond.executer_a_tort.borne_corriges à false, REGLE_INVERSIONS_EXECUTER) :
      parmi ces N relectures, les inversions vers EXÉCUTER (réponse proposée EXECUTER, corrigée vers une strate du
      plafond) se comptent À PART contre le nombre admis, fixé au calcul de l'étape 2 (etiquettes.inversions_vers_executer) ;
      une de trop ferme la fabrication de la même façon, même si les erreurs restent dans le plan.
    • Plan par sortie (calcul scellé avec etiquettes.plan_par_sortie, REGLE_PLAN_PAR_SORTIE) : tout ce qui précède se fait
      SORTIE PAR SORTIE, sur les N premières relectures des données du test (lot de etape3/a-relire.jsonl dans LOTS_TEST)
      proposées avec cette sortie (champ reponse) ; les inversions vers EXÉCUTER, sur celles de la sortie EXECUTER ; les
      portes se figent quand chaque sortie a ses N relectures, la justesse de chaque sortie (et tout critère qui compte
      sur elle) sur la borne mesurée de CETTE sortie ; une sortie au-delà de sa règle ferme la fabrication.
    • Sinon (moins de N relectures, aucune erreur ni inversion de trop) : en attente, rien n'est écrit."""
    import statistiques as st
    with ch.verrou():
        c = ch.lire()
        if c['etapes']['2']['etat'] != 'scellee' or c['etapes']['3']['etat'] != 'ouverte':
            raise Refus("La confirmation des portes se fait pendant l'étape 3 ouverte, sur le calcul scellé de l'étape 2.")
        deja = confirmation_portes(ch)
        if deja:
            return dict(deja, deja_decide=True)
        res = charger_json(ch.chemin('etape2', 'calcul', 'resultat.json'))
        par = charger_json(ch.chemin('etape2', 'calcul', 'parametres.json'))
        if not res or not par:
            raise Refus("Le calcul de l'étape 2 manque (etape2/calcul/resultat.json et parametres.json).")
        plan = (res.get('etiquettes') or {}).get('plan')
        tol = (res.get('etiquettes') or {}).get('borne_prevue')
        if not plan or tol is None:
            raise Refus("Le calcul scellé ne prévoit pas de tolérance des étiquettes (etiquettes.tolerance) : rien à confirmer.")
        m = par['methode']
        risque = m['risque']
        n_plan = int(plan.get('relectures', plan['relectures_sans_erreur']))
        permises = st.erreurs_permises(tol, risque, n_plan)
        par_sortie = bool(plan.get('par_sortie'))
        liste_a_relire = lire_lignes(ch.chemin('etape3', 'a-relire.jsonl'))
        a_relire = len(liste_a_relire)
        proposee = {x['id']: str(x.get('reponse') or '') for x in liste_a_relire}
        # REGLE_INVERSIONS_EXECUTER : la règle vient du calcul scellé (écrite avant les relectures), jamais recalculée ici.
        inv = (res.get('etiquettes') or {}).get('inversions_vers_executer')
        if par_sortie:
            # REGLE_PLAN_PAR_SORTIE : les N premières relectures de chaque sortie, dans le test seulement.
            lot_de = {x['id']: x.get('lot') for x in liste_a_relire}
            toutes = relectures_du_plan(ch)
            dans_test = [r for r in toutes if lot_de.get(r.get('id')) in LOTS_TEST]
            lues_s = {u: [r for r in dans_test if proposee.get(r.get('id')) == u][:n_plan] for u in plan['sorties']}
            a_relire_s = {u: sum(1 for x in liste_a_relire if x.get('lot') in LOTS_TEST and proposee[x['id']] == u) for u in plan['sorties']}
            lues = [r for u in plan['sorties'] for r in lues_s[u]]
            lues_inv = lues_s.get('EXECUTER', [])
            detail = {u: {'relues': len(lues_s[u]), 'erreurs': sum(1 for r in lues_s[u] if r.get('verdict') == 'corrige'),
                          'a_relire': a_relire_s[u]} for u in plan['sorties']}
            erreurs = sum(x['erreurs'] for x in detail.values())
            trop = [u for u, x in detail.items() if x['erreurs'] > permises]
            complet = all(x['relues'] >= n_plan for x in detail.values())
        else:
            lues = lues_inv = relectures_du_plan(ch)[:n_plan]
            erreurs = sum(1 for r in lues if r.get('verdict') == 'corrige')
            trop = ['tout'] if erreurs > permises else []
            complet = len(lues) >= n_plan
        base = {'borne_prevue': tol, 'relectures_plan': n_plan, 'erreurs_permises': permises, 'relues': len(lues),
                'erreurs': erreurs, 'a_relire': a_relire, 'regle': REGLE_BORNE_PREVUE}
        if par_sortie:
            base.update(par_sortie=detail, hors_test=len(toutes) - len(dans_test), regle_par_sortie=REGLE_PLAN_PAR_SORTIE)
        inversions = 0
        if inv:
            strates = set(inv['strates'])
            inversions = sum(1 for r in lues_inv if r.get('verdict') == 'corrige' and proposee.get(r.get('id')) == 'EXECUTER'
                             and str(r.get('correction') or '') in strates)
            base.update(inversions_vers_executer=inversions, inversions_permises=inv['permises'],
                        inversions_tolerance=inv['tolerance'], regle_inversions=inv['regle'])
        trop_inv = bool(inv) and inversions > inv['permises']
        if not trop and not trop_inv and not complet:
            if par_sortie:
                manque = '; '.join(f"{u} : encore {n_plan - x['relues']}" + ('' if x['a_relire'] >= n_plan else
                                   f" (etape3/a-relire.jsonl n'en propose que {x['a_relire']} dans le test)")
                                   for u, x in detail.items() if x['relues'] < n_plan)
                return dict(base, etat='en_attente', motif=f'relectures du test avant de figer les portes, par sortie ({n_plan} chacune) : {manque}')
            manque = ('' if a_relire >= n_plan else f" ; etape3/a-relire.jsonl n'en propose que {a_relire} : il en faut {n_plan}")
            return dict(base, etat='en_attente', motif=f'encore {n_plan - len(lues)} relectures avant de figer les portes{manque}')
        if par_sortie:
            for x in detail.values():
                x['borne_mesuree'] = st.borne_erreur(erreurs=x['erreurs'], relues=max(x['relues'], 1), risque=risque)
            borne = {u: x['borne_mesuree'] for u, x in detail.items()}
        else:
            borne = st.borne_erreur(erreurs=erreurs, relues=max(len(lues), 1), risque=risque)
        if trop or trop_inv:
            causes = []
            if trop and par_sortie:
                causes.append('écart à la borne prévue : ' + ' ; '.join(
                    f"{u} : {detail[u]['erreurs']} erreur{'s' if detail[u]['erreurs'] > 1 else ''} sur ses {detail[u]['relues']} premières "
                    f"relectures du test" for u in trop) + f" (le plan en permet {permises} sur {n_plan} par sortie pour une borne de {tol:.1%})")
            elif trop:
                causes.append(f"écart à la borne prévue : {erreurs} erreur{'s' if erreurs > 1 else ''} sur les {len(lues)} premières "
                              f"relectures (le plan en permet {permises} sur {n_plan} pour une borne de {tol:.1%})")
            if trop_inv:
                causes.append(f"plafond sans la borne des corrigés : {inversions} inversion{'s' if inversions > 1 else ''} vers EXÉCUTER "
                              f"sur les {len(lues_inv)} premières relectures{' des corrigés EXÉCUTER du test' if par_sortie else ''} "
                              f"(la règle en admet {inv['permises']} sur {inv['relectures']} pour une borne de {inv['tolerance']:.2%})")
            x = dict(base, a=maintenant(), etat='ecart', borne_mesuree=borne,
                     motif=' ; '.join(causes) + " : la fabrication est fermée jusqu'à la réouverture de l'étape 2 (nouvelle tolérance, nouveau calcul)")
            ecrire_json(ch.chemin('etape3', 'confirmation-portes.json'), x)
            ch.journaliser('fabrication_fermee', relues=len(lues), erreurs=erreurs, borne=borne, tolerance=tol,
                           **({'inversions_vers_executer': inversions} if inv else {}))
            return x
        reg = {k: {'valeur': v} for k, v in par['registre'].items()}
        ctx = _contexte_calcul(reg, par['pilote'], m)
        d = _dimensionner_facon(st, m, facon=ctx['facon'], criteres=ctx['criteres'], sorties=ctx['sorties'], unites=ctx['unites'],
                                regle_rares=ctx['regle_rares'], alphas=ctx['alphas'], puissance=ctx['puissance'],
                                marge_dim=res['marge_corriges']['dimension'], marge_seuil=borne,
                                toutes_au_vise=ctx['toutes_au_vise'], filtres=ctx['filtres'], n_impose=res['n_par_sortie'],
                                entrainement_min=ctx['entrainement_min'])
        profils = []
        for p in profils_defaut(ctx['criteres']) + list(par.get('profils') or []):
            profils.append({'nom': p['nom'], 'sorties': p['sorties'], 'executer_a_tort': p.get('executer_a_tort'),
                            'chance_livraison': chance_profil(d, p, LOTS_LIVRAISON)[0],
                            'chance_filtre1': chance_profil(d, p, ('selection',))[0], 'chance_filtre2': chance_profil(d, p, ('pre_evaluation',))[0],
                            'chance_recu': chance_profil(d, p)[0]})
        prevu = res['portes_par_critere']
        if par_sortie:
            motif = ('portes figées, chaque sortie sur sa borne mesurée dans le test (' + ' ; '.join(
                f"{u} {x['borne_mesuree']:.2%}, {x['erreurs']} erreur{'s' if x['erreurs'] > 1 else ''} sur {x['relues']}"
                for u, x in detail.items()) + f' ; prévue {tol:.1%})')
        else:
            motif = (f'portes figées sur la borne mesurée ({borne:.2%}, {erreurs} erreur sur {len(lues)} relectures ; prévue {tol:.1%})'
                     if erreurs == 1 else f'portes figées sur la borne mesurée ({borne:.2%}, {erreurs} erreurs sur {len(lues)} relectures ; prévue {tol:.1%})')
        x = dict(base, a=maintenant(), etat='figees', borne_mesuree=borne, motif=motif,
                 n_par_sortie=res['n_par_sortie'], tailles=res['tailles'],
                 portes={cid: {'libelle': y['libelle'], 'barre_testee': y['barre_testee'],
                               'lots': {l: {'n': y['lots'][l]['n'], 'k': y['lots'][l]['k'], 'texte': y['lots'][l]['texte'],
                                            'texte_prevu': prevu[cid]['lots'][l]['texte']} for l in LOTS_CALCUL}}
                        for cid, y in d['portes_par_critere'].items()},
                 chance_livraison_au_vise=round(d['chance_livraison_au_vise'], 4),
                 chance_filtres_au_vise={l: round(v, 4) for l, v in d['chance_filtres_au_vise'].items()} if ctx['filtres'] else None,
                 profils=profils, version_calcul=empreinte(os.path.join(ICI, 'statistiques.py')))
        ecrire_json(ch.chemin('etape3', 'confirmation-portes.json'), x)
        ch.journaliser('portes_figees', relues=len(lues), erreurs=erreurs, borne=borne, tolerance=tol)
        return x


# ─── Étape 4 : le tableau de bord de la boucle (E4.2.10, E4.2.11) et les sollicitations (E4.3) ──────────────────
# Le programme de la boucle écrit ses fichiers d'état sous etape4/ : essais.jsonl (un essai par ligne : essai,
# strategie, scores {définition: valeur}, vitesse_s, verdict retenu|promu|champion|rejete|arrete_tot, partiel, resume,
# detail), strategies.json ({id: {nom, idee, etat, essais, indice, chances, raison}}), machines.json ({a, machines:
# [{nom, carte, activite, donnees, vitesse, puissance_w, cout_eur, hors_ligne_depuis}], mesures: [...]}),
# sollicitations.jsonl. Le module les lit et les contrôle ; il n'y écrit aucun chiffre.

RYTHMES = {'essais': 3600, 'strategies': 3600, 'machines': 300}
# G3 : les quatre verdicts de la table d'attribution d'un essai.
VERDICTS_ATTRIBUTION = ('aide', 'nui', 'sans effet', 'confondu')


def age_s(iso, fin):
    try:
        return secondes(iso, fin)
    except (TypeError, ValueError):
        return None


def vue_boucle(ch):
    d = ch.chemin('etape4')
    essais = lire_lignes(os.path.join(d, 'essais.jsonl'))
    strategies = charger_json(os.path.join(d, 'strategies.json'))
    machines = charger_json(os.path.join(d, 'machines.json'))
    if not essais and not strategies and not machines:
        return None
    fin = maintenant()
    reg = charger_json(ch.chemin('registre.json'), {})
    arbre = lire_arbre(ch)
    colonnes = [t['id'] for t in arbre['termes']] or sorted({k for e in essais for k in (e.get('scores') or {})})
    minimums = {t['id']: (reg.get('b1.couche1') or {}).get('valeur') if t['couche'] == 1 else None for t in arbre['termes']}
    maj = {}
    for nom, chemin in (('essais', 'essais.jsonl'), ('strategies', 'strategies.json'), ('machines', 'machines.json')):
        p = os.path.join(d, chemin)
        if os.path.exists(p):
            a = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            age = age_s(a, fin)
            maj[nom] = {'a': a, 'fige': bool(age is not None and age > 3 * RYTHMES[nom])}
    depense = depense_recherche(d)
    return {'colonnes': colonnes, 'minimums': minimums, 'essais': essais, 'strategies': strategies or {}, 'machines': machines,
            'mis_a_jour': maj, 'controle': controler_boucle(essais, strategies or {}, machines or {}) + controler_depense(depense),
            'depense': depense, 'audits': derniers_audits(d), 'bibliotheque': resume_bibliotheque(ch),
            'sollicitations': [x for x in lire_lignes(os.path.join(d, 'sollicitations.jsonl')) if x.get('statut') != 'traitee']}


def resume_bibliotheque(ch):
    b = lire_bibliotheque(ch.nom, (charger_json(ch.chemin('chantier.json'), {}) or {}).get('categorie'))
    if not b.get('disponible'):
        return None
    return {'etablies_ici': len(b['etablies_ici']), 'a_reverifier': len(b['a_reverifier']), 'pistes': len(b['pistes_non_prouvees']), 'sorties': b['sorties'], 'harnais': len(b['harnais'])}


def derniers_audits(d):
    """G8 : le dernier audit de chaque porte (etape4/audits-portes.jsonl)."""
    der = {}
    for x in lire_lignes(os.path.join(d, 'audits-portes.jsonl')):
        der[str(x.get('porte'))] = {k: x.get(k) for k in ('porte', 'version', 'passe', 'echecs', 'a')}
    return [der[k] for k in sorted(der)]


def depense_recherche(d):
    """G5 : la dépense de chaque lignée, lue dans etape4/registre-budget-<lignée>.jsonl (format de
    registre-budget.py du moteur : en-tête d'identité, puis une ligne par dépense sous une étiquette unique)."""
    out = []
    for nom in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not (nom.startswith('registre-budget-') and nom.endswith('.jsonl')):
            continue
        lignes = lire_lignes(os.path.join(d, nom))
        if not lignes or 'identite' not in lignes[0]:
            out.append({'lignee': nom[16:-6], 'illisible': True})
            continue
        tete, entrees = lignes[0], lignes[1:]
        etiquettes = [e.get('etiquette') for e in entrees]
        sessions = sum(1 for e in entrees if e.get('sorte') == 'session' and e.get('role') == 'recherche')
        out.append({'lignee': (tete.get('identite') or {}).get('lignee') or nom[16:-6], 'identite': tete.get('identite'), 'plafond': tete.get('budget'),
                    'sessions_recherche': sessions, 'sessions_reflexion': sum(1 for e in entrees if e.get('sorte') == 'session' and e.get('role') == 'reflexion'),
                    'mesures': sum(1 for e in entrees if e.get('sorte') == 'mesure'), 'appels': sum(int(e.get('appels') or 0) for e in entrees if e.get('sorte') in ('mesure', 'appels')),
                    'doublons': sorted({x for x in etiquettes if etiquettes.count(x) > 1})})
    return out


def controler_depense(depense):
    pb = []
    for x in depense:
        if x.get('illisible'):
            pb.append({'section': 'essais', 'quoi': f"le registre de dépense de la lignée {x['lignee']} n'a pas d'en-tête d'identité"})
            continue
        if x['doublons']:
            pb.append({'section': 'essais', 'quoi': f"lignée {x['lignee']} : étiquettes de dépense en double ({', '.join(map(str, x['doublons'][:3]))}) — un résultat a pu en écraser un autre"})
        pl = x.get('plafond') or {}
        if pl.get('sessions_recherche') and x['sessions_recherche'] > pl['sessions_recherche'] + 2:
            pb.append({'section': 'essais', 'quoi': f"lignée {x['lignee']} : {x['sessions_recherche']} sessions de recherche pour un plafond de {pl['sessions_recherche']}"})
    plafonds = {json.dumps(x.get('plafond'), sort_keys=True) for x in depense if not x.get('illisible')}
    if len(plafonds) > 1:
        pb.append({'section': 'essais', 'quoi': 'les lignées comparées n\'ont pas le même plafond de dépense'})
    return pb


def controler_boucle(essais, strategies, machines):
    """E4.2.11 : incohérences entre les trois parties, informations manquantes, bugs d'affichage — par des comptes."""
    pb = []
    ids = {str(e.get('essai')) for e in essais}
    for m in (machines.get('mesures') or []):
        if m.get('essai') is not None and str(m['essai']) not in ids and m.get('etat') != 'en_cours':
            pb.append({'section': 'machines', 'quoi': f"la mesure de l'essai {m['essai']} est absente du tableau des essais"})
    par_strat = {}
    for e in essais:
        par_strat[e.get('strategie')] = par_strat.get(e.get('strategie'), 0) + 1
        if not e.get('resume'):
            pb.append({'section': 'journal', 'quoi': f"l'essai {e.get('essai')} n'a pas de résumé"})
        if not e.get('verdict'):
            pb.append({'section': 'essais', 'quoi': f"l'essai {e.get('essai')} n'a pas de verdict"})
        for k, v in (e.get('scores') or {}).items():
            if isinstance(v, (int, float)) and not 0 <= v <= 1:
                pb.append({'section': 'essais', 'quoi': f"valeur impossible pour {k} à l'essai {e.get('essai')} : {v}"})
        att = e.get('attribution')
        if att is not None:   # G3 : verdict par modification ; deux modifications non isolées = « confondu »
            if not isinstance(att, list) or not att:
                pb.append({'section': 'essais', 'quoi': f"l'essai {e.get('essai')} a une table d'attribution vide ou illisible"})
            else:
                for a in att:
                    if not isinstance(a, dict) or a.get('verdict') not in VERDICTS_ATTRIBUTION:
                        pb.append({'section': 'essais', 'quoi': f"verdict d'attribution inconnu à l'essai {e.get('essai')} : {a.get('verdict') if isinstance(a, dict) else a}"})
                if len(att) > 1 and any(isinstance(a, dict) and a.get('verdict') != 'confondu' for a in att):
                    pb.append({'section': 'essais', 'quoi': f"l'essai {e.get('essai')} attribue un effet à une modification non isolée ({len(att)} modifications : toutes « confondu »)"})
    for sid, st_ in strategies.items():
        if not st_.get('idee'):
            pb.append({'section': 'journal', 'quoi': f'la stratégie {sid} n\'a pas d\'idée écrite'})
        if st_.get('essais') is not None and st_['essais'] != par_strat.get(sid, 0):
            pb.append({'section': 'essais', 'quoi': f"la stratégie {sid} annonce {st_['essais']} essais, le tableau en a {par_strat.get(sid, 0)}"})
    champions = [e for e in essais if e.get('verdict') == 'champion']
    if len(champions) > 1:
        pb.append({'section': 'essais', 'quoi': f'{len(champions)} essais portent l\'étoile du champion'})
    for mc in (machines.get('machines') or []):
        if mc.get('donnees') is None and mc.get('activite') not in ('hors ligne',):
            pb.append({'section': 'machines', 'quoi': f"la machine {mc.get('nom')} n'a pas de relevé"})
    lignes = [mc.get('donnees') or 0 for mc in (machines.get('machines') or [])]
    total = (machines.get('total') or {}).get('donnees')
    if total is not None and lignes and total != sum(lignes):
        pb.append({'section': 'machines', 'quoi': f'le total ({total}) n\'est pas la somme des machines ({sum(lignes)})'})
    return pb


def cmd_controle_boucle(ch, a):
    """Le passage du vérificateur (E4.2.11) : rapport au journal ; il ne corrige rien."""
    v = vue_boucle(ch)
    pb = v['controle'] if v else []
    figees = [k for k, x in ((v or {}).get('mis_a_jour') or {}).items() if x['fige']]
    pb = pb + [{'section': k, 'quoi': 'section figée'} for k in figees]
    ch.journaliser('controle_tableau', problemes=len(pb), details=pb[:20])
    return {'problemes': pb, 'rien_a_signaler': not pb}



def cmd_traiter_sollicitation(ch, a):
    """E4.3 : la décision de l'utilisateur sur une sollicitation de la boucle, mot pour mot ; elle quitte la tête du volet."""
    sid = a.get('id')
    citation = str(a.get('citation') or '').strip()
    if not citation:
        raise Refus("Il faut la décision de l'utilisateur, mot pour mot (citation).")
    with ch.verrou():
        chemin = ch.chemin('etape4', 'sollicitations.jsonl')
        lignes = lire_lignes(chemin)
        if not any(x.get('id') == sid for x in lignes):
            raise Refus(f'Sollicitation inconnue : {sid}.')
        for x in lignes:
            if x.get('id') == sid:
                x.update(statut='traitee', decision={'citation': citation, 'a': maintenant(), 'choix': a.get('choix')})
        ecrire_atomique(chemin, ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in lignes))
        ch.journaliser('sollicitation_traitee', id=sid, citation=citation, choix=a.get('choix'))
        return {'id': sid, 'statut': 'traitee'}


# ---------------------------------------------------------------- G7 : la boucle d'usage après livraison
USAGE = 'etape5/usage'
USAGE_PROTEGES = ('scellee', '.graine', 'etiquettes', 'sonde.jsonl', 'jugements.jsonl', 'arrivees.jsonl', 'decisions/')
CHAMPS_USAGE = ('id', 'a', 'version', 'entree', 'sortie', 'source', 'consentement')


def usage_protege(rel):
    """Fichiers de la boucle d'usage tenus par le programme seul : ni l'agent (ecrire) ni la lecture libre (lire) n'y touchent."""
    rel = os.path.normpath(rel)
    if not rel.startswith(USAGE + '/'):
        return False
    reste = rel[len(USAGE) + 1:]
    return any(reste.startswith(p) for p in USAGE_PROTEGES)


def usage_regles(reg):
    g = greffes().get('g7_usage') or {}
    return {'part_scellee': float(valeur(reg, 'usage.part_scellee', g.get('part_scellee', 0.5), obligatoire=False)),
            'scellee_min': int(valeur(reg, 'usage.scellee_min', g.get('scellee_min_defaut', 200), obligatoire=False)),
            'consultations_max': int(valeur(reg, 'usage.consultations_max', g.get('consultations_max', 5), obligatoire=False))}


def usage_graine(ch):
    p = ch.chemin(USAGE, '.graine')
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(os.urandom(16).hex())
    with open(p) as f:
        return f.read().strip()


def usage_part(graine, generation, ident, fraction):
    h = hashlib.sha256(f'{graine}|{generation}|{ident}'.encode()).hexdigest()
    return 'scellee' if int(h[:8], 16) / 0xFFFFFFFF < fraction else 'sonde'


def cmd_usage_importer(ch, a):
    """G7 : importe un lot du journal des consignes réelles écrit par le livrable en test (format : usage-interface.md).
    Chaque nouvelle consigne est rangée À L'ARRIVÉE, avant que quiconque la voie : part scellée (tirage secret) ou part
    visible de la sonde. Lignes invalides refusées une par une ; doublons (même id) ignorés."""
    c = ch.lire()
    if c['etapes']['4']['etat'] != 'scellee' and not (c['sous_etapes'].get('E5.5') or {}).get('etat') == 'validee':
        raise Refus("La boucle d'usage ne démarre qu'après l'examen réussi (étape 4 scellée) ou la recette (E5.5 validée) : rien n'est journalisé avant.")
    src = str(a.get('fichier') or '')
    if not os.path.isabs(src):
        src = ch.chemin(os.path.normpath(src.lstrip('/')))
    if not os.path.isfile(src):
        raise Refus(f'Lot introuvable : {src}.')
    reg = charger_json(ch.chemin('registre.json'), {})
    r = usage_regles(reg)
    with ch.verrou():
        etat = charger_json(ch.chemin(USAGE, 'etat.json'), {'generation': 1, 'consultations': 0})
        vus = {x.get('id') for x in lire_lignes(ch.chemin(USAGE, 'arrivees.jsonl'))}
        graine = usage_graine(ch)
        refus, nouvelles = [], {'scellee': [], 'sonde': []}
        for i, x in enumerate(lire_lignes(src)):
            manque = [k for k in CHAMPS_USAGE if x.get(k) in (None, '')]
            if manque or not isinstance(x.get('entree'), dict) or not isinstance(x.get('sortie'), dict) or x.get('consentement') is not True or 'etiquette' in x:
                refus.append({'ligne': i + 1, 'pourquoi': ('champs manquants : ' + ', '.join(manque)) if manque else ('pas de consentement' if x.get('consentement') is not True else ('une étiquette ne vient jamais du livrable' if 'etiquette' in x else 'entree et sortie sont des objets'))})
                continue
            if x['id'] in vus:
                continue
            vus.add(x['id'])
            part = usage_part(graine, etat['generation'], x['id'], r['part_scellee'])
            nouvelles[part].append({**x, 'generation': etat['generation']} if part == 'scellee' else x)
            ajouter_ligne(ch.chemin(USAGE, 'arrivees.jsonl'), {'id': x['id'], 'a': maintenant(), 'part': part, 'generation': etat['generation']})
        for x in nouvelles['scellee']:
            ajouter_ligne(ch.chemin(USAGE, 'scellee.jsonl'), x)
        for x in nouvelles['sonde']:
            ajouter_ligne(ch.chemin(USAGE, 'sonde.jsonl'), x)
        ecrire_json(ch.chemin(USAGE, 'etat.json'), etat)
        ch.journaliser('usage_importe', lot=os.path.basename(src), scellees=len(nouvelles['scellee']), sonde=len(nouvelles['sonde']), refusees=len(refus))
    return {'scellees': len(nouvelles['scellee']), 'sonde': len(nouvelles['sonde']), 'refusees': refus[:20]}


def cmd_usage_a_etiqueter(ch, a):
    """G7 : pour l'agent d'étiquetage SEUL (jamais la sonde ni un chercheur) : les consignes scellées sans étiquette."""
    par = str(a.get('par') or '').strip()
    if not par:
        raise Refus("Qui étiquette ? (par : le nom de l'agent d'étiquetage ; jamais la sonde ni un chercheur)")
    faites = {x['id'] for x in lire_lignes(ch.chemin(USAGE, 'etiquettes.jsonl'))}
    a_faire = [x for x in lire_lignes(ch.chemin(USAGE, 'scellee.jsonl')) if x['id'] not in faites]
    n = min(int(a.get('n') or 20), 50)
    ch.journaliser('usage_vu_pour_etiquetage', par=par, ids=[x['id'] for x in a_faire[:n]])
    return {'restantes': len(a_faire), 'donnees': [{k: x.get(k) for k in ('id', 'entree', 'sortie')} for x in a_faire[:n]]}


def cmd_usage_etiqueter(ch, a):
    par = str(a.get('par') or '').strip()
    ident, etiquette = a.get('id'), a.get('etiquette')
    if not par or ident in (None, '') or etiquette in (None, ''):
        raise Refus('Il faut id, etiquette et par (l’agent d’étiquetage).')
    if str(par).lower().startswith(('sonde', 'chercheur')):
        raise Refus("La sonde et les chercheurs n'étiquettent jamais la part scellée.")
    with ch.verrou():
        if ident not in {x['id'] for x in lire_lignes(ch.chemin(USAGE, 'scellee.jsonl'))}:
            raise Refus(f'{ident} n’est pas dans la part scellée.')
        if ident in {x['id'] for x in lire_lignes(ch.chemin(USAGE, 'etiquettes.jsonl'))}:
            raise Refus(f'{ident} est déjà étiquetée.')
        ajouter_ligne(ch.chemin(USAGE, 'etiquettes.jsonl'), {'id': ident, 'etiquette': etiquette, 'par': par, 'a': maintenant()})
        ch.journaliser('usage_etiquete', id=ident, par=par)
    return {'id': ident, 'etiquette': etiquette}


def _p_signe(g, p):
    n, k = g + p, min(g, p)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def cmd_usage_juger(ch, a):
    """G7 : une modification proposée par la sonde est jugée sur le banc (test apparié rendu par la boucle) ET sur la part
    réelle scellée, étiquetée après coup. Décisions des deux versions sur la part scellée : fichiers rendus par le
    programme verrouillé (etape5/usage/decisions/<nom>.jsonl : {id, decision}), jamais par un agent."""
    reg = charger_json(ch.chemin('registre.json'), {})
    r = usage_regles(reg)
    risque = methode(reg)['risque']
    modif = str(a.get('modification') or '').strip()
    if not modif:
        raise Refus('Quelle modification ? (modification)')
    banc = a.get('banc') or {}
    if banc.get('test') != 'signe' or not all(isinstance(banc.get(k), int) for k in ('hausses', 'baisses')):
        raise Refus('Le jugement sur le banc manque : banc = {test: signe, hausses, baisses} (test apparié de la boucle, sur le banc).')
    lire_dec = lambda nom: {x['id']: x.get('decision') for x in lire_lignes(ch.chemin(USAGE, 'decisions', os.path.basename(str(nom))))}
    base, cand = lire_dec(a.get('base') or ''), lire_dec(a.get('candidat') or '')
    with ch.verrou():
        etat = charger_json(ch.chemin(USAGE, 'etat.json'), {'generation': 1, 'consultations': 0})
        if etat['consultations'] >= r['consultations_max']:
            raise Refus(f"Part scellée usée ({etat['consultations']} jugements sur {r['consultations_max']}) : renouvelle-la par des consignes neuves (usage_renouveler) avant de juger encore.")
        etiq = {x['id']: x['etiquette'] for x in lire_lignes(ch.chemin(USAGE, 'etiquettes.jsonl'))}
        ids = [x['id'] for x in lire_lignes(ch.chemin(USAGE, 'scellee.jsonl')) if x.get('generation', 1) == etat['generation'] and x['id'] in etiq]
        manque = [i for i in ids if i not in base or i not in cand]
        if manque:
            raise Refus(f'Décisions manquantes sur la part scellée pour {len(manque)} consigne(s) (ex. {manque[0]}) : le programme verrouillé doit rejouer les deux versions sur toute la part.')
        hausses = sum(1 for i in ids if cand[i] == etiq[i] and base[i] != etiq[i])
        baisses = sum(1 for i in ids if cand[i] != etiq[i] and base[i] == etiq[i])
        p_reel, p_banc = _p_signe(hausses, baisses), _p_signe(banc['hausses'], banc['baisses'])
        recul_banc = p_banc <= risque and banc['baisses'] > banc['hausses']
        if len(ids) < r['scellee_min']:
            verdict = 'non_jugeable'
            pourquoi = f"part scellée étiquetée trop petite : {len(ids)} sur {r['scellee_min']}"
        elif recul_banc:
            verdict, pourquoi = 'refusee', f"recul significatif sur le banc ({banc['hausses']} mieux, {banc['baisses']} moins bien, p = {p_banc:.3g})"
        elif p_reel <= risque and hausses > baisses:
            verdict, pourquoi = 'adoptee', f"gain significatif sur l'usage réel ({hausses} mieux, {baisses} moins bien, p = {p_reel:.3g}) sans recul sur le banc"
        elif p_reel <= risque and baisses > hausses:
            verdict, pourquoi = 'refusee', f"recul significatif sur l'usage réel ({hausses} mieux, {baisses} moins bien, p = {p_reel:.3g})"
        else:
            verdict, pourquoi = 'non_tranchee', f"pas d'écart significatif sur l'usage réel ({hausses} mieux, {baisses} moins bien, p = {p_reel:.3g})"
        if verdict != 'non_jugeable':
            etat['consultations'] += 1
            ecrire_json(ch.chemin(USAGE, 'etat.json'), etat)
        ligne = {'a': maintenant(), 'modification': modif, 'verdict': verdict, 'pourquoi': pourquoi, 'n_scellees': len(ids), 'generation': etat['generation'],
                 'reel': {'hausses': hausses, 'baisses': baisses, 'p': round(p_reel, 6)}, 'banc': {'hausses': banc['hausses'], 'baisses': banc['baisses'], 'p': round(p_banc, 6)}}
        ajouter_ligne(ch.chemin(USAGE, 'jugements.jsonl'), ligne)
        ch.journaliser('usage_juge', modification=modif, verdict=verdict, n_scellees=len(ids))
    return {'modification': modif, 'verdict': verdict, 'pourquoi': pourquoi, 'consultations': etat['consultations'], 'consultations_max': r['consultations_max']}


def cmd_usage_renouveler(ch, a):
    """G7 : la part scellée s'use à force d'être consultée : une
    nouvelle génération commence ; l'ancienne reste scellée, retirée, jamais montrée."""
    citation = str(a.get('citation') or '').strip()
    if not citation:
        raise Refus("Le renouvellement se fait sur l'accord de l'utilisateur, mot pour mot (citation).")
    with ch.verrou():
        etat = charger_json(ch.chemin(USAGE, 'etat.json'), {'generation': 1, 'consultations': 0})
        etat = {'generation': etat['generation'] + 1, 'consultations': 0}
        ecrire_json(ch.chemin(USAGE, 'etat.json'), etat)
        ch.journaliser('usage_renouvele', generation=etat['generation'], citation=citation)
    return etat


def vue_usage(ch):
    if not os.path.isdir(ch.chemin(USAGE)):
        return None
    etat = charger_json(ch.chemin(USAGE, 'etat.json'), {'generation': 1, 'consultations': 0})
    reg = charger_json(ch.chemin('registre.json'), {})
    r = usage_regles(reg)
    scellees = [x for x in lire_lignes(ch.chemin(USAGE, 'scellee.jsonl')) if x.get('generation', 1) == etat['generation']]
    etiq = {x['id'] for x in lire_lignes(ch.chemin(USAGE, 'etiquettes.jsonl'))}
    jug = lire_lignes(ch.chemin(USAGE, 'jugements.jsonl'))
    return {'arrivees': len(lire_lignes(ch.chemin(USAGE, 'arrivees.jsonl'))), 'scellees': len(scellees), 'etiquetees': sum(1 for x in scellees if x['id'] in etiq),
            'sonde': len(lire_lignes(ch.chemin(USAGE, 'sonde.jsonl'))), 'scellee_min': r['scellee_min'], 'consultations': etat['consultations'],
            'consultations_max': r['consultations_max'], 'generation': etat['generation'],
            'jugements': [{k: x.get(k) for k in ('modification', 'verdict', 'pourquoi')} for x in jug[-5:]]}


def lire_bibliotheque(chantier, categorie=None):
    """G2 : la bibliothèque entre chantiers, vue d'un chantier (lecture seule). Racine :
    $LA_BOUCLE_BIBLIOTHEQUE, sinon le réglage bibliotheque."""
    racine = os.environ.get('LA_BOUCLE_BIBLIOTHEQUE') or REGLAGES.get('bibliotheque') or None
    if not racine or not os.path.isdir(racine):
        return {'racine': racine, 'disponible': False}
    lecons = lire_lignes(os.path.join(racine, 'lecons.jsonl'))
    harnais = lire_lignes(os.path.join(racine, 'harnais.jsonl'))
    court = lambda x: {k: x.get(k) for k in ('id', 'chantier', 'categorie', 'situation', 'lecon', 'detail', 'sens')}
    verifiee_ici = lambda x: any(v.get('chantier') == chantier and v.get('verdict') == 'confirmee' for v in x.get('verifications') or [])
    etablies = [x for x in lecons if x.get('statut') == 'etablie']
    ici = [court(x) for x in etablies if x.get('chantier') == chantier or verifiee_ici(x)]
    ailleurs = [court(x) for x in etablies if not (x.get('chantier') == chantier or verifiee_ici(x))]
    ailleurs.sort(key=lambda x: (0 if categorie and x.get('categorie') == categorie else 1, x.get('id') or ''))
    return {'racine': racine, 'disponible': True, 'etablies_ici': ici, 'a_reverifier': ailleurs,
            'pistes_non_prouvees': [court(x) for x in lecons if x.get('statut') == 'a_prouver'],
            'sorties': sum(1 for x in lecons if x.get('statut') == 'sortie'),
            'harnais': [{k: h.get(k) for k in ('chantier', 'categorie', 'tag', 'famille', 'pourquoi')} for h in harnais]}


def cmd_bibliotheque(ch, a):
    c = ch.lire()
    b = lire_bibliotheque(ch.nom, c.get('categorie'))
    ch.journaliser('bibliotheque_lue', disponible=b.get('disponible'), ici=len(b.get('etablies_ici') or []), a_reverifier=len(b.get('a_reverifier') or []))
    return b


PORTES = ('1', '2', '3')


def cmd_audit_porte(ch, a):
    """G8 : la liste d'audit des échecs connus (methode.json, greffes_h2.g8_audit) avant une porte.
    Chaque point a son verdict (ok, echec, sans objet) et sa preuve ; un seul échec ferme la porte."""
    g = greffes().get('g8_audit') or {}
    porte = str(a.get('porte') or '')
    if porte not in PORTES:
        raise Refus('porte : 1, 2 ou 3.')
    reponses = a.get('reponses') or []
    if not isinstance(reponses, list):
        raise Refus('reponses : une liste {id, verdict, preuve}.')
    ids = [p['id'] for p in g.get('points') or []]
    par_id = {str(r.get('id')): r for r in reponses if isinstance(r, dict)}
    manquants = [i for i in ids if i not in par_id]
    if manquants:
        raise Refus(f"Points sans réponse : {', '.join(manquants)}. Chaque point de la liste reçoit un verdict et une preuve.")
    for i in ids:
        r = par_id[i]
        if r.get('verdict') not in (g.get('verdicts') or ('ok', 'echec', 'sans objet')):
            raise Refus(f"Point {i} : verdict ok, echec ou sans objet.")
        if not str(r.get('preuve') or '').strip():
            raise Refus(f'Point {i} : il faut la preuve (fichier, ligne, chiffre).')
    echecs = [{'id': i, 'preuve': par_id[i]['preuve']} for i in ids if par_id[i]['verdict'] == 'echec']
    ligne = {'a': maintenant(), 'porte': porte, 'version': a.get('version'), 'passe': not echecs, 'echecs': echecs,
             'reponses': [{'id': i, 'verdict': par_id[i]['verdict'], 'preuve': par_id[i]['preuve']} for i in ids]}
    with ch.verrou():
        ajouter_ligne(ch.chemin('etape4', 'audits-portes.jsonl'), ligne)
        ch.journaliser('audit_porte', porte=porte, version=a.get('version'), passe=not echecs, echecs=[e['id'] for e in echecs])
    return {'porte': porte, 'passe': not echecs, 'echecs': echecs}


def cmd_verifier_contexte(ch, a):
    """G6 : un dossier (ou fichier) du chantier qu'on s'apprête à remettre à un agent chercheur ne
    contient aucun verdict du juge, vérifié par le NOM puis par le CONTENU (marqueurs de methode.json, greffes_h2.g6_garde)."""
    g = greffes().get('g6_garde') or {}
    mode = a.get('mode') or g.get('mode_defaut') or 'aucun'   # par défaut aucun agent ne voit l'examen
    if mode not in ('agreges', 'aucun'):
        raise Refus('mode : agreges ou aucun.')
    rel = os.path.normpath(str(a.get('dossier') or '').lstrip('/'))
    if rel.startswith('..') or rel in ('', '.'):
        raise Refus('Dossier refusé (relatif au chantier, sous lui).')
    cible = ch.chemin(rel)
    if not os.path.exists(cible):
        raise Refus(f"{rel} n'existe pas.")
    cles = list(g.get('cles_toujours') or []) + (list(g.get('cles_examen') or []) if mode == 'aucun' else [])
    marqueurs = [re.compile(r'"%s"\s*:' % re.escape(k)) for k in cles] + [re.compile(t) for t in g.get('textes') or []]
    noms = [re.compile(n) for n in g.get('noms') or []]
    fichiers = [cible] if os.path.isfile(cible) else [os.path.join(d, f) for d, _, fs in os.walk(cible) for f in sorted(fs)]
    base = cible if os.path.isdir(cible) else os.path.dirname(cible)
    fuites = []
    for f in sorted(fichiers):
        r = os.path.relpath(f, base)
        n = next((x.pattern for x in noms if x.search(r)), None)
        if n:
            fuites.append({'fichier': os.path.relpath(f, ch.dossier), 'par': 'nom', 'marqueur': n})
            continue
        try:
            with open(f, encoding='utf-8', errors='replace') as h:
                t = h.read(5_000_000)
        except OSError:
            continue
        x = next((m for m in (mm.search(t) for mm in marqueurs) if m), None)
        if x:
            fuites.append({'fichier': os.path.relpath(f, ch.dossier), 'par': 'contenu', 'marqueur': x.group(0), 'contexte': t[max(0, x.start() - 60):x.start() + 100]})
    ch.journaliser('verification_contexte', dossier=rel, mode=mode, fichiers=len(fichiers), fuites=len(fuites), details=fuites[:10])
    return {'dossier': rel, 'mode': mode, 'fichiers': len(fichiers), 'propre': not fuites, 'fuites': fuites}


# ─── E2.2.1 : la diversité des données générées.
# Générique : n'importe quel champ texte d'un JSONL, des cases facultatives (plan de quotas), des graines réelles facultatives.


# Mots élidés devant une apostrophe : « l'onglet » se compte « onglet ».
_ELISIONS = {'l', 'd', 'j', 'm', 'n', 's', 't', 'c', 'qu', 'jusqu', 'lorsqu', 'puisqu', 'quoiqu'}


def _mots(t):
    out = []
    for m in re.findall(r"[\w'’]+", str(t).lower()):
        parts = [x for x in re.split(r"['’]", m) if x]
        while len(parts) > 1 and parts[0] in _ELISIONS:
            parts = parts[1:]
        if parts:
            out.append("'".join(parts))   # « aujourd'hui » reste un seul mot
    return out


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def mesurer_diversite(lignes, champ, champ_case=None, plan=None, graines=None, seuils=None, mots_exclus=None):
    """mots_exclus : mots retirés du modèle des vraies données (graines) avant de mesurer leur couverture, par exemple
    les noms propres d'un cas réel qu'aucun lot inventé ne peut contenir (registre generation.mots_exclus)."""
    seuils = seuils or {}
    exclus = {m for x in (mots_exclus or []) for m in _mots(x)}
    textes = [str(l.get(champ) or '').strip() for l in lignes if str(l.get(champ) or '').strip()]
    n = len(textes)
    if n == 0:
        raise Refus(f'Aucune donnée avec le champ « {champ} ».')
    norm = [' '.join(_mots(t)) for t in textes]
    distinctes = len(set(norm))
    ens = [frozenset(_mots(t)) for t in textes]
    limite = seuils.get('quasi_doublon_jaccard', 0.8)
    echantillon = ens[:: max(1, n // 2000)]   # au plus ~2 000 comparées deux à deux (déterministe)
    quasi = sum(1 for i in range(len(echantillon)) for j in range(i + 1, len(echantillon))
                if echantillon[i] != echantillon[j] and _jaccard(echantillon[i], echantillon[j]) >= limite)
    paires = len(echantillon) * (len(echantillon) - 1) // 2 or 1
    tous_mots = [m for t in textes for m in _mots(t)]
    r = {'n': n, 'distinctes': distinctes, 'part_distinctes': round(distinctes / n, 4),
         'quasi_doublons_pour_mille_paires': round(1000 * quasi / paires, 3),
         'premiers_mots_distincts': len({(_mots(t) or [''])[0] for t in textes}),
         'vocabulaire': len(set(tous_mots)), 'mots_par_donnee': round(len(tous_mots) / n, 2)}
    motifs = []
    if r['part_distinctes'] < seuils.get('part_distinctes_min', 0.9):
        motifs.append(f"trop de doublons exacts ({r['part_distinctes']:.0%} de données distinctes)")
    if r['quasi_doublons_pour_mille_paires'] > seuils.get('quasi_doublons_max_pour_mille', 5):
        motifs.append('trop de quasi-doublons')
    if champ_case:
        compte = {}
        for l in lignes:
            k = str(l.get(champ_case))
            compte[k] = compte.get(k, 0) + 1
        r['par_case'] = compte
        if plan:
            manque = {k: q - compte.get(k, 0) for k, q in plan.items() if compte.get(k, 0) < q}
            r['cases_sous_quota'] = manque
            if manque:
                motifs.append(f'{len(manque)} case(s) du plan sous leur quota')
    if graines:
        g_textes = [str(x.get(champ) or '') for x in graines if str(x.get(champ) or '').strip()]
        voc = set(tous_mots)
        g_mots = [m for t in g_textes for m in _mots(t) if m not in exclus]
        absents = sorted({m for m in g_mots if m not in voc})
        proches = [max((_jaccard(frozenset(_mots(t)), e) for e in echantillon), default=0) for t in g_textes]
        r['graines'] = {'n': len(g_textes), 'mots_reels_jamais_generes': absents[:50],
                        'part_mots_reels_couverts': round(sum(1 for m in g_mots if m in voc) / len(g_mots), 4) if g_mots else None,
                        'proximite_moyenne': round(sum(proches) / len(proches), 4) if proches else None,
                        'mots_exclus': sorted(exclus)}
        if r['graines']['part_mots_reels_couverts'] is not None and r['graines']['part_mots_reels_couverts'] < seuils.get('mots_reels_couverts_min', 0.8):
            motifs.append('le vocabulaire des vraies données est mal couvert par la génération')
    r['passe'], r['motifs'] = not motifs, motifs
    return r


def cmd_diversite(ch, a):
    """E2.2.1, E2.3, E3.1 : mesure la diversité d'un lot généré (doublons, quasi-doublons, couverture du plan de
    quotas, écart aux vraies données servant de graines), contre les seuils de methode.json (generation.seuils),
    changeables par le registre (generation.seuils). Les mots du registre generation.mots_exclus (noms propres du cas
    réel) sortent du modèle des graines."""
    rel = os.path.normpath(str(a.get('fichier') or '').lstrip('/'))
    if rel.startswith('..') or not rel.endswith('.jsonl'):
        raise Refus('fichier : un .jsonl du chantier (chemin relatif).')
    reg = charger_json(ch.chemin('registre.json'), {})
    seuils = dict((charger_json(os.path.join(ICI, 'methode.json'), {}).get('generation') or {}).get('seuils') or {})
    seuils.update(valeur(reg, 'generation.seuils', {}, obligatoire=False) or {})
    plan = valeur(reg, 'generation.plan', None, obligatoire=False)
    graines = None
    if a.get('graines'):
        g = os.path.normpath(str(a['graines']).lstrip('/'))
        if g.startswith('..'):
            raise Refus('graines : un .jsonl du chantier.')
        graines = lire_lignes(ch.chemin(g))
    exclus = valeur(reg, 'generation.mots_exclus', [], obligatoire=False) or []
    if not isinstance(exclus, list):
        raise Refus('generation.mots_exclus : une liste de mots.')
    r = mesurer_diversite(lire_lignes(ch.chemin(rel)), a.get('champ') or 'texte', a.get('champ_case'), plan, graines, seuils,
                          [str(x) for x in exclus])
    r.update({'fichier': rel, 'a': maintenant(), 'seuils': seuils})
    with ch.verrou():
        ecrire_json(ch.chemin(os.path.dirname(rel), 'diversite.json'), r)
        ch.journaliser('diversite', fichier=rel, passe=r['passe'], motifs=r['motifs'])
    return r


def cmd_signaler(ch, a):
    """Un message court à l'opérateur absent, par la commande de notification des réglages (désactivée par défaut)."""
    import subprocess
    n = REGLAGES['notification']
    if not n.get('active') or not n.get('commande'):
        return {'envoye': False, 'raison': 'notification désactivée (réglage notification.active)'}
    texte = str(a.get('texte') or '')[:600]
    try:
        r = subprocess.run(list(n['commande']) + [texte], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return {'envoye': False, 'raison': str(e)[:200]}
    return {'envoye': r.returncode == 0, 'raison': None if r.returncode == 0 else f'code {r.returncode}'}


COMMANDES = {
    'signaler': cmd_signaler,
    'ouvrir': cmd_ouvrir, 'etat': cmd_etat, 'avancer': cmd_avancer, 'decision': cmd_decision, 'categorie': cmd_categorie,
    'ecrire': cmd_ecrire, 'lire': cmd_lire, 'rouvrir': cmd_rouvrir, 'registre': cmd_registre, 'evenement': cmd_evenement,
    'terme': cmd_terme, 'relecture': cmd_relecture, 'accord': cmd_accord,
    'sceller': cmd_sceller, 'rouvrir_etape': cmd_rouvrir_etape, 'mesures': cmd_mesures,
    'calcul': cmd_calcul, 'confirmer_portes': cmd_confirmer_portes, 'diversite': cmd_diversite, 'relire': cmd_relire, 'controle_boucle': cmd_controle_boucle, 'traiter_sollicitation': cmd_traiter_sollicitation,
    'comptes': cmd_comptes, 'agent': cmd_agent, 'suivi': cmd_suivi, 'depense': cmd_depense, 'arreter_agent': cmd_arreter_agent,
    'relancer': cmd_relancer, 'verifier_contexte': cmd_verifier_contexte, 'audit_porte': cmd_audit_porte, 'bibliotheque': cmd_bibliotheque,
    'usage_importer': cmd_usage_importer, 'usage_a_etiqueter': cmd_usage_a_etiqueter, 'usage_etiqueter': cmd_usage_etiqueter,
    'usage_juger': cmd_usage_juger, 'usage_renouveler': cmd_usage_renouveler,
}


def executer(commande, args, racine):
    if commande == 'parcours':
        return {'parcours': parcours(), 'categories': categories()}
    if commande == 'liste':
        return {'chantiers': sorted(n for n in os.listdir(racine) if os.path.exists(os.path.join(racine, n, 'chantier.json')))} if os.path.isdir(racine) else {'chantiers': []}
    if commande not in COMMANDES:
        raise Refus(f"Commande inconnue : {commande}.")
    return COMMANDES[commande](Chantier(racine, args.get('chantier')), args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('commande')
    ap.add_argument('--racine', default=os.environ.get('LA_BOUCLE_V2_RACINE') or RACINE_DEFAUT)
    o = ap.parse_args(argv)
    brut = sys.stdin.read() if not sys.stdin.isatty() else ''
    try:
        args = json.loads(brut) if brut.strip() else {}
        if not isinstance(args, dict):
            raise Refus('Les paramètres sont un objet JSON.')
        print(json.dumps({'ok': True, 'resultat': executer(o.commande, args, o.racine)}, ensure_ascii=False))
        return 0
    except Refus as r:
        print(json.dumps({'ok': False, 'refus': str(r)}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as e:
        print(json.dumps({'ok': False, 'refus': f'Paramètres illisibles : {e}'}, ensure_ascii=False))
        return 0


if __name__ == '__main__':
    sys.exit(main())
