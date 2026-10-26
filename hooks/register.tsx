// Mode « La boucle » v2 : conduit un chantier de la méthode de bout en bout.
// /la-boucle <chantier> rattache CETTE session au chantier : elle seule reçoit le volet de contrôle, la
// bande au-dessus de l'invite, les consignes de l'agent et ses outils. L'état vit dans les fichiers du chantier,
// tenus par le programme (programme/boucle.py) : le mod n'en garde qu'une copie pour dessiner.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Agent, Fichier, Rattachement, SousEtape, Suivi, Vue } from '../types'
import { PROGRAMME_RELATIF, SSH_WINDOWS, argvPour, lireReponse, transitions } from './programme'
import type { Reponse } from './programme'
import { ETAT, QUI, bienvenue, contexteReprise, ditPret, heure, protocole, sansRappels } from './textes'

const P = 'la-boucle-v2'
const rattachement = atom({ plugin: 'la-boucle-v2', key: 'rattachement' } as const, null)
const vue = atom({ plugin: 'la-boucle-v2', key: 'vue' } as const, null)
const erreur = atom({ plugin: 'la-boucle-v2', key: 'erreur' } as const, null)
const deplie = atom({ plugin: 'la-boucle-v2', key: 'deplie' } as const, [])
const fichier = atom({ plugin: 'la-boucle-v2', key: 'fichier' } as const, null)
const derniereReponse = atom({ plugin: 'la-boucle-v2', key: 'derniereReponse' } as const, null)
const ouverts = atom({ plugin: 'la-boucle-v2', key: 'ouverts' } as const, [])
const suivi = atom({ plugin: 'la-boucle-v2', key: 'suivi' } as const, null)
const donneeRelue = atom({ plugin: 'la-boucle-v2', key: 'donneeRelue' } as const, null)
const PANE_RELECTURE = 'la-boucle-v2-relecture'
const nomCourt = atom({ plugin: 'la-boucle-v2', key: 'nomCourt' } as const, false)
const dernierMessage = atom({ plugin: 'la-boucle-v2', key: 'dernierMessage' } as const, null)
const ABSENT_MS = 15 * 60_000

const PANE = 'la-boucle-v2'
const PANE_FICHIER = 'la-boucle-v2-fichier'
const cleSession = (id: string) => `session:${id}`

// Les outils de l'agent, déclarés seulement quand la session se rattache. Chacun est une commande du programme.
type Outil = { nom: string; commande: string; description: string; schema: Record<string, unknown>; requis: string[] }
const OUTILS: Outil[] = [
  {
    nom: 'etat', commande: 'etat', requis: [],
    description: "La boucle : l'état du chantier (sous-étapes, ce qui attend, décisions, registre), lu dans ses fichiers.",
    schema: {},
  },
  {
    nom: 'decision', commande: 'decision', requis: ['sous_etape', 'resume', 'citation'],
    description: "La boucle : enregistre une décision de l'utilisateur sous sa sous-étape, avec ses mots exacts et l'heure. `point` pour un point du cadrage (E1.4 : p01 à p16). `option` : la lettre choisie (A, B, C, D) ou « autre » quand il a répondu autre chose qu'une option proposée.",
    schema: {
      sous_etape: { type: 'string', description: 'ex. E1.2' },
      point: { type: 'string', description: 'ex. p03 (seulement pour une sous-étape à points)' },
      resume: { type: 'string', description: 'La décision en une ligne' },
      citation: { type: 'string', description: "Les mots de l'utilisateur, mot pour mot" },
      option: { type: 'string', enum: ['A', 'B', 'C', 'D', 'autre'] },
      rouvert: { type: 'boolean', description: 'true quand cette décision rouvre un point déjà tranché' },
    },
  },
  {
    nom: 'avancer', commande: 'avancer', requis: ['sous_etape', 'etat'],
    description: "La boucle : change l'état d'une sous-étape : en_cours, a_valider (ton travail est présenté, il attend l'utilisateur), validee (seulement sur sa réponse explicite, citée mot pour mot). Valider ouvre la sous-étape suivante.",
    schema: {
      sous_etape: { type: 'string' },
      etat: { type: 'string', enum: ['en_cours', 'a_valider', 'validee'] },
      citation: { type: 'string', description: "Obligatoire pour validee : la réponse de l'utilisateur, mot pour mot" },
    },
  },
  {
    nom: 'categorie', commande: 'categorie', requis: ['categorie', 'raison', 'citation'],
    description: "La boucle (E1.3) : enregistre la catégorie du besoin choisie par l'utilisateur ; ses sous-étapes s'ajoutent au parcours. Catégories : classique, agent-interaction-logicielle, ou « aucune ».",
    schema: {
      categorie: { type: 'string', enum: ['classique', 'agent-interaction-logicielle', 'aucune'] },
      raison: { type: 'string', description: 'Ta raison, en une ligne' },
      citation: { type: 'string', description: "La réponse de l'utilisateur, mot pour mot" },
    },
  },
  {
    nom: 'ecrire', commande: 'ecrire', requis: ['chemin', 'contenu'],
    description: "La boucle : écrit une sortie de sous-étape dans le dossier du chantier (chemin relatif, sous etape1/ à etape5/, ex. etape1/besoin.md). La version précédente est gardée ; un fichier scellé est refusé.",
    schema: {
      chemin: { type: 'string' },
      contenu: { type: 'string' },
      pourquoi: { type: 'string', description: 'Ce qui change et pourquoi (quand le fichier existait)' },
    },
  },
  {
    nom: 'lire', commande: 'lire', requis: ['chemin'],
    description: 'La boucle : lit un fichier du dossier du chantier (chemin relatif).',
    schema: { chemin: { type: 'string' } },
  },
  {
    nom: 'rouvrir', commande: 'rouvrir', requis: ['sous_etape', 'raison'],
    description: "La boucle : rouvre une sous-étape (la discussion y revient). Seulement à la demande de l'utilisateur ; dis pourquoi.",
    schema: { sous_etape: { type: 'string' }, raison: { type: 'string' } },
  },
  {
    nom: 'registre', commande: 'registre', requis: ['cle', 'valeur', 'citation'],
    description: "La boucle : inscrit une règle du chantier au registre (un seuil, une valeur), statut « propose » (seuils de qualité, scellés à l'étape 2) ou « fixe ». Clé en minuscules, ex. qualite.min, vitesse.max_s, b1.couche1.",
    schema: {
      cle: { type: 'string' },
      valeur: { description: 'Nombre, texte ou liste' },
      statut: { type: 'string', enum: ['propose', 'fixe'] },
      libelle: { type: 'string', description: 'La règle en clair' },
      sous_etape: { type: 'string' },
      citation: { type: 'string', description: "Les mots de l'utilisateur, mot pour mot" },
    },
  },
  {
    nom: 'terme', commande: 'terme', requis: ['id', 'libelle'],
    description: "La boucle (E1.5) : ajoute ou change un terme de l'arbre des définitions. Couche 1 = les sorties (sans parent) ; un terme enfant donne son parent. etat : redecoupe (on le découpe en sous-termes), liste (fixé par une liste fermée, donner `liste`), modele (laissé au jugement du modèle), a_definir. citation obligatoire sauf pour a_definir. Les seuils B1/B2 ne se fixent que pour la couche racine (registre b1.couche1, b2.couche1), jamais pour une sous-couche.",
    schema: {
      id: { type: 'string', description: 'ex. N1, N2A, N3B' },
      libelle: { type: 'string' },
      definition: { type: 'string', description: 'La définition en une ou deux phrases' },
      parent: { type: 'string' },
      etat: { type: 'string', enum: ['a_definir', 'redecoupe', 'liste', 'modele'] },
      liste: { type: 'array', items: { type: 'string' } },
      citation: { type: 'string', description: "Les mots de l'utilisateur, mot pour mot" },
    },
  },
  {
    nom: 'relecture', commande: 'relecture', requis: ['passe', 'relecteur', 'reponses'],
    description: "La boucle (E1.7) — réservé à un relecteur à l'aveugle : dépose tes réponses, {exemple: {critère: réponse}}. Passe 1 : relecteurs A et B ; passe 2 : C et D. Tu ne vois pas les réponses de l'autre relecteur.",
    schema: {
      passe: { type: 'integer', enum: [1, 2] },
      relecteur: { type: 'string', description: 'Une lettre : A, B, C ou D' },
      reponses: { type: 'object', description: '{ "ex1": { "N1": "risque", "N2A": "oui" }, ... }' },
    },
  },
  {
    nom: 'accord', commande: 'accord', requis: [],
    description: "La boucle (E1.7) : l'accord des relecteurs, critère par critère et passe par passe, et la liste des désaccords (exemple, critère, réponse de chacun), calculés par le programme.",
    schema: {},
  },
  {
    nom: 'sceller', commande: 'sceller', requis: ['etape'],
    description: "La boucle : demande le scellement d'une étape dont toutes les sous-étapes sont validées. Rend le récapitulatif (décisions avec les mots de l'utilisateur, documents et empreintes, seuils scellés ou laissés « proposés ») à lui présenter. Rien n'est verrouillé avant sa confirmation par le canal de confirmation (hors de portée des agents) ; l'étape reste « à sceller » jusque-là.",
    schema: { etape: { type: 'integer', enum: [1, 2, 3, 4, 5] } },
  },
  {
    nom: 'rouvrir_etape', commande: 'rouvrir_etape', requis: ['etape', 'raison', 'citation', 'confirme'],
    description: "La boucle : rouvre une étape scellée. Les étapes qui en dépendent sont relancées et les seuils scellés redeviennent « proposés ». Seulement sur l'accord explicite de l'utilisateur, après lui avoir dit ce que ça relance : citation mot pour mot, confirme=true.",
    schema: {
      etape: { type: 'integer', enum: [1, 2, 3, 4, 5] },
      raison: { type: 'string' },
      citation: { type: 'string', description: "L'accord explicite de l'utilisateur, mot pour mot" },
      confirme: { type: 'boolean' },
    },
  },
  {
    nom: 'comptes', commande: 'comptes', requis: ['action'],
    description: "La boucle : branche ou débranche un compte Claude au Moteur du chantier — le Moteur, ce sont les comptes Claude sur lesquels partent ses agents (les comptes des réglages ou du relevé des comptes, ex. compte-a, compte-b : sans nouvelle connexion) — ou voit les comptes branchés.",
    schema: { action: { type: 'string', enum: ['voir', 'brancher', 'debrancher'] }, compte: { type: 'string' } },
  },
  {
    nom: 'agent', commande: 'agent', requis: ['nom'],
    description: "La boucle : crée ou met à jour la fiche d'un agent (ou d'un programme, genre=programme) qui travaille pour le chantier : rôle, sous-étape, sur quoi, où il en est, état (travaille, attend, fini, panne, arrete). À la création d'un agent, le programme choisit le compte du Moteur qui a le plus de quota (ou compte_voulu, si l'utilisateur l'a choisi) : lance l'agent sur ce compte, avec LA_BOUCLE_CHANTIER=<chantier> dans son environnement.",
    schema: {
      nom: { type: 'string', description: 'Nom de session (ex. redacteur-definitions)' },
      role: { type: 'string' },
      sous_etape: { type: 'string' },
      quoi: { type: 'string' },
      ou_en_est: { type: 'string' },
      etat: { type: 'string', enum: ['travaille', 'attend', 'fini', 'panne', 'arrete'] },
      genre: { type: 'string', enum: ['agent', 'programme'] },
      ou: { type: 'string', description: 'ici, ou le nom de la machine qui le fait tourner' },
      session: { type: 'string', description: 'Nom de la session tmux (claude-<nom> par défaut)' },
      lien: { type: 'string', description: 'Lien Remote Control de sa conversation' },
      compte_voulu: { type: 'string' },
      relance: { type: 'array', items: { type: 'string' }, description: 'La commande qui relance ce travail s’il bloque (lanceur et ses arguments)' },
    },
  },
  {
    nom: 'depense', commande: 'depense', requis: ['action', 'passe'],
    description: "La boucle : prevoir une passe payante (rôle, fournisseur, modèle, relectures par donnée, coût unitaire mesuré, coût total estimé, durée, part du quota de la semaine) ; accepter seulement sur l'accord de l'utilisateur dans le chat (citation mot pour mot, montant accepté) ; depenser pour noter ce qui est réellement parti. Une passe qui dépasse le montant accepté s'arrête et revient vers l'utilisateur.",
    schema: {
      action: { type: 'string', enum: ['prevoir', 'accepter', 'depenser'] },
      passe: { type: 'string' },
      sous_etape: { type: 'string' },
      role: { type: 'string' },
      fournisseur: { type: 'string' },
      modele: { type: 'string' },
      relectures_par_donnee: { type: 'number' },
      cout_unitaire_eur: { type: 'number' },
      cout_estime_eur: { type: 'number' },
      duree_estimee: { type: 'string' },
      quota_pct: { type: 'number' },
      montant_accepte_eur: { type: 'number' },
      montant_eur: { type: 'number' },
      citation: { type: 'string' },
    },
  },
  {
    nom: 'diversite', commande: 'diversite', requis: ['fichier'],
    description: "La boucle (E2.2.1, E2.3, E3.1) : le programme mesure la diversité d'un lot généré (.jsonl du chantier) : doublons, quasi-doublons, couverture du plan de quotas (registre generation.plan), écart aux vraies données servant de graines (sans les mots du registre generation.mots_exclus, noms propres du cas réel ; « l'onglet » compte « onglet ») ; verdict contre les seuils (methode.json, registre generation.seuils). Ne mesure jamais toi-même.",
    schema: {
      fichier: { type: 'string', description: 'le lot, relatif au chantier (ex. etape2/pilote/donnees.jsonl)' },
      champ: { type: 'string', description: 'le champ texte de chaque ligne (défaut : texte)' },
      champ_case: { type: 'string', description: 'le champ qui dit la case du plan (facultatif)' },
      graines: { type: 'string', description: 'les vraies données, .jsonl relatif au chantier (facultatif)' },
    },
  },
  {
    nom: 'calcul', commande: 'calcul', requis: [],
    description: "La boucle (E2.14) : le programme calcule les tailles des lots, les seuils des trois portes, le minimum par sortie et la courbe de la chance d'être reçu, une porte par critère (justesse de chaque sortie, plafond d'exécution à tort, B1), depuis le registre (barre.par_sortie, niveau_vise.par_sortie, plafond.executer_a_tort, repli barre.qualite / niveau_vise.qualite ; calcul.facon prudent|juste, calcul.toutes_portes_au_vise, calcul.portes_filtres (portes 1 et 2 = filtres au seuil de la porte 3, la livraison seule garantit), cas_rares.regle, etiquettes.tolerance, b1.couche1, lots.entrainement_min : le cours hors sélection, au moins cette valeur, à parts égales entre sorties) et etape2/pilote/mesures.json ; paramètre facultatif profils [{nom, sorties, executer_a_tort}] : la chance de chaque profil. Le plafond d'exécution à tort reçoit la borne des corrigés comme les justesses, sauf registre plafond.executer_a_tort.borne_corriges à false : il est alors testé sans elle, et etiquettes.inversions_vers_executer donne le nombre d'inversions vers EXÉCUTER que les relectures du plan admettent (règle écrite avant elles). Registre etiquettes.plan_par_sortie (true ; défaut false) : le plan de fiabilité compte ses relectures PAR SORTIE dans le test seulement (examen blanc, examen, vérification), etiquettes.plan.relectures par sortie, la règle des inversions vers EXÉCUTER se dit sur les corrigés EXÉCUTER du test dans l'unité des strates du plafond, et le calcul reste « à confirmer » à l'étape 3. Les tableaux à montrer (tailles, seuils, profils, prudent / juste) sont dans le champ tableaux, chiffres compris : recopie-les tels quels. Un pilote trop petit pour la tolérance des étiquettes : les portes se posent avec la borne prévue (etiquettes.tolerance), champ a_confirmer « à confirmer par N relectures à l'étape 3 » (pas un compromis). Ne calcule jamais toi-même.",
    schema: {
      profils: {
        type: 'array',
        items: {
          type: 'object',
          properties: { nom: { type: 'string' }, sorties: { type: 'object' }, executer_a_tort: { type: 'number' }, b1: { type: 'number' } },
          required: ['nom', 'sorties'],
        },
      },
    },
  },
  {
    nom: 'confirmer_portes', commande: 'confirmer_portes', requis: [],
    description: "La boucle (E3.2, E3.3) : après les relectures de fiabilité du banc, le programme relance le calcul scellé de l'étape 2 avec la borne d'erreur des étiquettes MESURÉE sur les premières relectures du banc, autant que le plan en compte (etiquettes.plan, registre etiquettes.erreurs_permises, 0 par défaut) : borne au plus égale à la tolérance → les portes se figent (etape3/confirmation-portes.json) ; plus d'erreurs que le plan n'en permet, ou (plafond sans la borne des corrigés) plus d'inversions vers EXÉCUTER que la règle du calcul n'en admet → l'écart ferme la fabrication (plus de dépense, pas de scellement de l'étape 3) jusqu'à la réouverture de l'étape 2 ; sinon, en attente. Plan par sortie (calcul scellé avec etiquettes.plan_par_sortie) : tout se lit sortie par sortie, sur les premières relectures des données du test proposées avec cette sortie (lot et reponse de etape3/a-relire.jsonl), chaque sortie sur SA borne mesurée ; une sortie au-delà de sa règle ferme la fabrication. Ne calcule jamais toi-même.",
    schema: {},
  },
  {
    nom: 'traiter_sollicitation', commande: 'traiter_sollicitation', requis: ['id', 'citation'],
    description: "La boucle (E4.3) : enregistre la décision de l'utilisateur sur une sollicitation de la boucle (plateau, tas caché trop petit, quota, garde-fou, proposition d'un agent), mot pour mot ; elle quitte la tête du volet. Les décisions qui engagent se confirment ensuite sur son téléphone.",
    schema: { id: { type: 'string' }, citation: { type: 'string' }, choix: { type: 'string' } },
  },
  {
    nom: 'usage_importer', commande: 'usage_importer', requis: ['fichier'],
    description: "La boucle (E5.6, greffe G7) : importe un lot du journal des consignes réelles écrit par le livrable en test (format : programme/usage-interface.md). Le programme scelle sa part tirée au hasard DÈS L'ARRIVÉE, avant que quiconque la voie ; le reste va à la sonde (etape5/usage/sonde.jsonl). Seulement après l'examen réussi.",
    schema: { fichier: { type: 'string', description: 'le lot (chemin absolu, ou relatif au chantier)' } },
  },
  {
    nom: 'usage_a_etiqueter', commande: 'usage_a_etiqueter', requis: ['par'],
    description: "La boucle (E5.6, G7) — réservé à l'agent d'étiquetage, jamais à la sonde ni à un chercheur : les consignes scellées sans étiquette (au plus 50).",
    schema: { par: { type: 'string' }, n: { type: 'number' } },
  },
  {
    nom: 'usage_etiqueter', commande: 'usage_etiqueter', requis: ['id', 'etiquette', 'par'],
    description: "La boucle (E5.6, G7) — réservé à l'agent d'étiquetage : la bonne réponse d'une consigne scellée, après coup.",
    schema: { id: { type: 'string' }, etiquette: { type: 'string' }, par: { type: 'string' } },
  },
  {
    nom: 'usage_juger', commande: 'usage_juger', requis: ['modification', 'banc', 'base', 'candidat'],
    description: "La boucle (E5.6, G7) : juge une modification proposée par la sonde, sur le banc (banc = {test: signe, hausses, baisses}, le test apparié de la boucle) ET sur la part réelle scellée étiquetée (décisions des deux versions rejouées par le programme verrouillé : base et candidat = fichiers de etape5/usage/decisions/). Verdict : adoptee, refusee, non_tranchee ou non_jugeable ; chaque jugement use la part scellée.",
    schema: { modification: { type: 'string' }, base: { type: 'string' }, candidat: { type: 'string' }, banc: { type: 'object', properties: { test: { type: 'string', enum: ['signe'] }, hausses: { type: 'number' }, baisses: { type: 'number' } } } },
  },
  {
    nom: 'usage_renouveler', commande: 'usage_renouveler', requis: ['citation'],
    description: "La boucle (E5.6, G7) : la part scellée est usée (trop de jugements) : une nouvelle génération commence avec les consignes neuves, sur l'accord de l'utilisateur cité mot pour mot.",
    schema: { citation: { type: 'string' } },
  },
  {
    nom: 'bibliotheque', commande: 'bibliotheque', requis: [],
    description: "La boucle (greffe G2) : la bibliothèque entre chantiers, vue de ce chantier (lecture seule) : leçons établies ici (preuve appariée), leçons d'autres chantiers à revérifier sur ce banc (des hypothèses, jamais des faits), pistes non prouvées, harnais gardés.",
    schema: {},
  },
  {
    nom: 'audit_porte', commande: 'audit_porte', requis: ['porte', 'reponses'],
    description: "La boucle (greffe G8) : avant une porte (1 : entraînement → pré-évaluation ; 2 : pré-évaluation → examen ; 3 : examen → livrable), enregistre la liste d'audit des échecs connus de Harness² : un verdict (ok, echec, sans objet) et une preuve pour CHAQUE point (A1-A3 sélection, B1-B3 modification restrictive, C1-C3 exécution) ; un seul échec ferme la porte. A3 = le biais vers le refus (les sorties prudentes montent pendant que les sorties d'action baissent).",
    schema: { porte: { type: 'string', enum: ['1', '2', '3'] }, version: { type: 'string' }, reponses: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, verdict: { type: 'string', enum: ['ok', 'echec', 'sans objet'] }, preuve: { type: 'string' } }, required: ['id', 'verdict', 'preuve'] } } },
  },
  {
    nom: 'verifier_contexte', commande: 'verifier_contexte', requis: ['dossier'],
    description: "La boucle (greffe G6) : avant de remettre un dossier ou un fichier du chantier à un agent chercheur (étapes 3 et 4), vérifie par le NOM et par le CONTENU qu'il ne porte aucun verdict du juge (examen, sélection, pré-évaluation, vérification, recorrection). S'il n'est pas propre, rien n'est remis : c'est une fuite à corriger.",
    schema: { dossier: { type: 'string', description: 'chemin relatif au chantier' }, mode: { type: 'string', enum: ['aucun', 'agreges'], description: "« aucun » par défaut : rien de l'examen, même agrégé ; « agreges » seulement si le chantier le demande" } },
  },
  {
    nom: 'controle_boucle', commande: 'controle_boucle', requis: [],
    description: "La boucle (E4.2.11) — vérificateur du tableau : cherche les incohérences entre les essais, les machines et le journal, les informations manquantes et les sections figées ; ne corrige rien, le rapport va au journal.",
    schema: {},
  },
]

// Réglages du module (userConfig de plugin.json) : l'hôte (vide = programme local), l'interpréteur Python, et
// l'emplacement du programme sur l'hôte distant. Les réglages du programme lui-même sont dans boucle-module.json.
const HOTE_DEFAUT = ''
const REGLAGE = { python: 'python3', distant: '' }
const clientSsh = atom({ plugin: 'la-boucle-v2', key: 'ssh' } as const, null)

/** Où joindre le programme : en local (dans le dossier du module), sinon par SSH (celui de Git sous Windows). */
async function transport($: EngineInterface, h: string): Promise<{ programme: string; ssh: string }> {
  const programme = `${$.plugin.root}/${PROGRAMME_RELATIF}`
  let ssh = await read($, clientSsh)
  if (ssh === null) {
    if (h) {
      const existe = (chemin: string) => $.fs.stat(chemin).then(() => true, () => false)
      ssh = (await existe(SSH_WINDOWS)) ? SSH_WINDOWS : 'ssh'
    } else ssh = 'ssh'
    const c = ssh
    await update($, clientSsh, () => c)
  }
  return { programme, ssh }
}

/** Appelle une commande du programme ; un échec de transport devient un refus lisible, jamais une exception. */
async function appeler<T>($: EngineInterface, h: string, commande: string, args: Record<string, unknown>): Promise<Reponse<T>> {
  try {
    const { programme, ssh } = await transport($, h)
    const r = await $.process.run(argvPour(h, programme, commande, ssh, REGLAGE.python, REGLAGE.distant), { stdin: JSON.stringify(args), timeoutMs: 30_000 })
    return lireReponse<T>(r.stdout, r.stderr, r.exitCode)
  } catch (err) {
    return { ok: false, refus: `Programme injoignable : ${String(err).slice(0, 300)}` }
  }
}

async function rafraichir($: EngineInterface, h: string): Promise<Vue | null> {
  const r = await read($, rattachement)
  if (!r) return null
  const rep = await appeler<Vue>($, h, 'etat', { chantier: r.chantier })
  if (!rep.ok) {
    await update($, erreur, () => rep.refus)
    return null
  }
  await update($, vue, () => rep.resultat)
  await update($, erreur, () => null)
  return rep.resultat
}

async function relever($: EngineInterface, h: string) {
  const r = await read($, rattachement)
  if (!r) return
  const rep = await appeler<Suivi>($, h, 'suivi', { chantier: r.chantier })
  if (!(rep.ok && Array.isArray(rep.resultat?.agents) && rep.resultat.comptes && rep.resultat.budget)) return
  const avant = await read($, suivi)
  await update($, suivi, () => rep.resultat)
  if (!avant || r.role !== 'utilisateur') return
  // un travail fini revient dans le chat ; bloqué ou en panne, il est relancé tout seul ; si l'utilisateur est
  // absent, un message court par la commande de notification réglée (désactivée par défaut). Seule la session rattachée le fait.
  const { finis, bloques } = transitions(avant.agents, rep.resultat.agents)
  const vu = await read($, dernierMessage)
  const absent = vu === null || (await $.clock.now()) - vu > ABSENT_MS
  for (const a of finis) {
    await $.prompt.submit({ text: `[la-boucle] ${a.role ?? a.nom} a fini${a.sous_etape ? ` (${a.sous_etape})` : ''} : lis son travail et présente-le à l'utilisateur, dans le chat.` })
    if (absent) await signaler($, h, r.chantier, `${r.chantier} : ${a.role ?? a.nom} a fini, je te le présente dans la conversation.`)
  }
  for (const a of bloques) {
    let relance = ''
    if (a.relancable) {
      const rr = await appeler($, h, 'relancer', { chantier: r.chantier, nom: a.nom })
      relance = rr.ok ? ' Relancé, rien à faire.' : ` ${rr.refus}`
    }
    $.ui.toast(`${a.role ?? a.nom} : bloqué ou en panne.${relance}`)
    await signaler($, h, r.chantier, `${r.chantier} : ${a.role ?? a.nom} est bloqué ou en panne.${relance || ' Je regarde.'}`)
  }
}

async function signaler($: EngineInterface, h: string, chantier: string, texte: string) {
  // La notification est un réglage du programme (désactivée par défaut) : sans commande réglée, rien ne part.
  await appeler($, h, 'signaler', { chantier, texte })
}

async function brancher($: EngineInterface, h: string, chantier: string, compte: string, action: 'brancher' | 'debrancher') {
  const rep = await appeler($, h, 'comptes', { chantier, action, compte })
  if (!rep.ok) $.ui.toast(rep.refus)
  await relever($, h)
}

async function arreterAgent($: EngineInterface, h: string, chantier: string, nom: string) {
  const rep = await appeler<{ arret: string }>($, h, 'arreter_agent', { chantier, nom })
  $.ui.toast(rep.ok ? `${nom} : ${rep.resultat.arret}` : `${nom} : ${rep.refus}`)
  await relever($, h)
}

async function declarerOutils($: EngineInterface) {
  for (const o of OUTILS) {
    await $.tool.register({
      name: o.nom,
      description: o.description,
      isDeferred: false,
      inputSchema: { type: 'object', properties: o.schema, required: o.requis },
    })
  }
}

async function rattacher($: EngineInterface, h: string, chantier: string, role: Rattachement['role']): Promise<{ vue: Vue } | { refus: string }> {
  const session = await $.session.id()
  const rep = await appeler<Vue>($, h, 'ouvrir', { chantier, session, role })
  if (!rep.ok) return { refus: rep.refus }
  const ratt: Rattachement = { chantier, role, depuis: new Date(await $.clock.now()).toISOString() }
  await update($, rattachement, () => ratt)
  await update($, vue, () => rep.resultat)
  await update($, erreur, () => null)
  await $.store.set(cleSession(session), ratt)
  await declarerOutils($)
  if (role === 'utilisateur') void $.ui.open({ id: PANE, title: `La boucle — ${chantier}` })
  return { vue: rep.resultat }
}

async function journal($: EngineInterface, h: string, type: string, donnees: Record<string, unknown>) {
  const r = await read($, rattachement)
  if (!r) return
  await appeler($, h, 'evenement', { chantier: r.chantier, type, donnees })
}

async function ouvrirFichier($: EngineInterface, h: string, chantier: string, chemin: string) {
  const rep = await appeler<{ contenu: string; chemin: string }>($, h, 'lire', { chantier, chemin })
  const f: Fichier = rep.ok ? { chemin, contenu: rep.resultat.contenu } : { chemin, contenu: rep.refus }
  await update($, fichier, () => f)
  await $.ui.open({ id: PANE_FICHIER, title: chemin })
}

/** Le résumé d'une décision sur une ligne du volet. */
function resumeCourt(t: string): string {
  const u = sansRappels(t).replace(/\s+/g, ' ')
  return u.length > 80 ? u.slice(0, 77) + '…' : u
}

/** « etape1/fiche-de-notation.md » → « fiche de notation ». */
function nomDocument(chemin: string): string {
  return (chemin.split('/').pop() ?? chemin).replace(/\.md$/, '').replace(/[-_]/g, ' ')
}

async function allerA($: EngineInterface, s: SousEtape) {
  await $.prompt.submit({ text: `Reprenons la sous-étape ${s.id} — ${s.titre}.`, asUser: true })
}

async function rouvrirSousEtape($: EngineInterface, s: SousEtape) {
  await $.prompt.submit({ text: `Je veux rouvrir la sous-étape ${s.id} — ${s.titre}.`, asUser: true })
}

async function rouvrirPoint($: EngineInterface, sid: string, point: string, titre: string) {
  await $.prompt.submit({ text: `Je veux rouvrir le point ${point} du cadrage (${sid}) : ${titre}.`, asUser: true })
}

async function ouvrirRelecture($: EngineInterface, h: string, chantier: string) {
  const rep = await appeler<{ donnee: { id: string; lot?: string; donnee: unknown; reponse: unknown } | null }>($, h, 'relire', { chantier, action: 'suivante' })
  await update($, donneeRelue, () => (rep.ok ? rep.resultat.donnee : null))
  await $.ui.open({ id: PANE_RELECTURE, title: 'Relecture du banc' })
}

async function noterRelecture($: EngineInterface, h: string, chantier: string, id: string, verdict: 'ok' | 'corrige', correction?: string) {
  const rep = await appeler($, h, 'relire', { chantier, action: 'noter', id, verdict, correction })
  if (!rep.ok) $.ui.toast(rep.refus)
  await ouvrirRelecture($, h, chantier)
  await rafraichir($, h)
}

async function basculer($: EngineInterface, cle: string) {
  await update($, ouverts, l => (l.includes(cle) ? l.filter(x => x !== cle) : [...l, cle]))
}

/** Le repère de chaque état de sous-étape, en tête de sa ligne (la couleur porte le sens, cf. couleur()). */
const REPERE: Record<string, string> = { a_faire: '○', en_cours: '▶', a_valider: '◆', validee: '✓', scellee: '✓' }

const ETAT_TERME: Record<string, string> = { a_definir: 'à définir', redecoupe: 'redécoupé', liste: 'fixé par liste', modele: 'laissé au modèle' }
const duree = (x: number | null | undefined) =>
  x == null ? 'non mesuré' : x < 60 ? `${x} s` : x < 3600 ? `${Math.round(x / 60)} min` : `${Math.floor(x / 3600)} h ${String(Math.round((x % 3600) / 60)).padStart(2, '0')}`
const jetons = (x: number | null | undefined) => (x == null ? 'non mesuré' : x >= 1_000_000 ? `${(x / 1_000_000).toFixed(1)} M` : x >= 1000 ? `${Math.round(x / 1000)} k` : String(x))
/** Un travail bloqué ou en panne passe en rouge : panne déclarée, ou plus aucune activité depuis 20 min. */
const enRouge = (a: Agent, maintenant: number) =>
  a.bloque === true ||
  a.etat === 'panne' || (a.etat === 'travaille' && !!a.activite && maintenant - Date.parse(a.activite) > 20 * 60_000)
const depuisQuand = (iso: string | undefined, maintenant: number) => {
  if (!iso) return ''
  const m = Math.max(0, Math.round((maintenant - Date.parse(iso)) / 60_000))
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`
}
const LOTS: Record<string, string> = { entrainement: 'entraînement (dont sélection)', selection: 'sélection (contrôle caché)', pre_evaluation: 'pré-évaluation (examen blanc)', examen: 'examen', verification: 'vérification' }
const pct = (x: number | null) => (x == null ? 'non mesuré' : `${Math.round(x * 100)} %`)

export const register: Register = (on, options) => {
  const H = typeof options?.hote === 'string' && options.hote ? options.hote : HOTE_DEFAUT
  if (typeof options?.python === 'string' && options.python) REGLAGE.python = options.python
  if (typeof options?.programme_distant === 'string') REGLAGE.distant = options.programme_distant
  const NOM_COURT = options?.nom_court === true
  const CMD = NOM_COURT ? '/la-boucle' : '/la-boucle-v2'

  on('session.start', async ($, e, next) => {
    // /la-boucle-v2, et /la-boucle (le même) seulement si l'option nom_court est allumée : sinon le nom court
    // reste libre pour un autre module, qui ne pourrait plus démarrer si celui-ci le prenait.
    await $.command.register({
      name: 'la-boucle-v2',
      description: 'La boucle (v2) : ouvrir ou reprendre un chantier dans cette session (volet de contrôle, étapes, décisions)',
      argumentHint: '<chantier> | off',
    })
    await update($, nomCourt, () => NOM_COURT)
    if (NOM_COURT) {
      await $.command.register({
        name: 'la-boucle',
        description: 'La boucle : ouvrir ou reprendre un chantier dans cette session (volet de contrôle, étapes, décisions)',
        argumentHint: '<chantier> | off',
      })
    }
    // Une session déjà rattachée (reprise, rechargement) ou un agent lancé par la boucle pour un chantier.
    const session = await $.session.id()
    const connu = (await $.store.get(cleSession(session))) as Rattachement | undefined
    const pourAgent = await $.env.get('LA_BOUCLE_CHANTIER')
    if (connu) {
      await rattacher($, H, connu.chantier, connu.role)
      // Journal : quelles surfaces la session dessine (le volet manquait sur l'écran distant).
      const surfaces = await $.session.surfaces().catch(() => null)
      if (surfaces) await journal($, H, 'surfaces', { surfaces, volets: await $.ui.panes().catch(() => null) })
    }
    else if (pourAgent) await rattacher($, H, pourAgent, 'agent')
    $.clock.every(30_000, () => void rafraichir($, H))
    $.clock.every(60_000, () => void relever($, H).catch(() => undefined))
    return next(e)
  })

  on('command.run', { command: ['la-boucle', 'la-boucle-v2'] }, async ($, e, next) => {
    // /la-boucle appartient à un autre module éventuel tant que nom_court est éteinte : on ne le lui prend pas.
    if (e.command === 'la-boucle' && !(await read($, nomCourt))) return next(e)
    const arg = e.args.trim()
    const r = await read($, rattachement)
    if (arg === 'off') {
      if (!r) return { text: "Cette session n'est rattachée à aucun chantier." }
      await journal($, H, 'session_detachee', { session: await $.session.id() })
      await update($, rattachement, () => null)
      await update($, vue, () => null)
      await $.store.delete(cleSession(await $.session.id()))
      await $.ui.close({ id: PANE })
      await $.ui.close({ id: PANE_FICHIER })
      return { text: `Session détachée du chantier « ${r.chantier} » : elle redevient une session normale.` }
    }
    if (arg === '') {
      if (r) {
        await $.ui.open({ id: PANE, title: `La boucle — ${r.chantier}` })
        const v = await rafraichir($, H)
        return { text: `Chantier « ${r.chantier} » — ce qui t'attend : ${v?.attend?.quoi ?? 'rien'}.` }
      }
      const rep = await appeler<{ chantiers: string[] }>($, H, 'liste', {})
      const liste = rep.ok ? rep.resultat.chantiers : []
      return { text: `Ouvre un chantier : ${CMD} <chantier>.${liste.length ? ` Chantiers existants : ${liste.join(', ')}.` : ''}` }
    }
    const nom = arg.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
    if (!nom) return { text: 'Nom de chantier invalide.' }
    if (r && r.chantier !== nom) return { text: `Cette session est déjà rattachée au chantier « ${r.chantier} » : ${CMD} off d'abord.` }
    const res = await rattacher($, H, nom, 'utilisateur')
    void relever($, H).catch(() => undefined)
    if ('refus' in res) return { text: `La boucle n'a pas pu ouvrir le chantier : ${res.refus}` }
    const v = res.vue
    // E1.1 : tant que la bienvenue n'est pas validée, elle s'affiche, chantier neuf ou repris.
    const bienvenueOuverte = v.etapes[0]?.sous_etapes.find(x => x.id === 'E1.1')?.etat === 'en_cours'
    if (v.neuf || bienvenueOuverte) return { text: bienvenue(v), context: ["Le mode La boucle vient d'ouvrir un chantier neuf ; le bandeau de bienvenue ci-dessus est affiché. Ne pose aucune question : attends que l'utilisateur dise qu'il est prêt."] }
    return { text: `Chantier « ${nom} » repris — ce qui t'attend : ${v.attend?.quoi ?? 'rien'}.`, context: [contexteReprise(v)] }
  })

  on('prompt.compose', async ($, e, next) => {
    const res = await next(e)
    const r = await read($, rattachement)
    const v = await read($, vue)
    if (!r || !v) return res
    return { sections: [...res.sections, { id: 'la-boucle-v2:protocole', text: protocole(v, r.role), scope: 'session' as const }] }
  })

  on('prompt.submit', async ($, e, next) => {
    const r = await read($, rattachement)
    const kind = e.origin?.kind
    const parUtilisateur = kind === 'composer' || kind === 'bridge' || kind === 'sdk'
    if (!r || r.role !== 'utilisateur' || !parUtilisateur || e.text.trim().startsWith('/')) return next(e)
    const maintenant = await $.clock.now()
    await update($, dernierMessage, () => maintenant)
    const avant = await read($, derniereReponse)
    const v = await read($, vue)
    const encours = v?.etapes.flatMap(x => x.sous_etapes).find(s => s.etat === 'en_cours' || s.etat === 'a_valider')
    // Mesures : le temps de réponse de l'utilisateur, sous la sous-étape où il répond.
    await journal($, H, 'message_utilisateur', {
      sous_etape: encours?.id ?? null,
      longueur: e.text.length,
      temps_reponse_s: avant ? Math.round((maintenant - avant) / 1000) : null,
    })
    // E1.1 : le message qui dit qu'il est prêt valide la bienvenue, mot pour mot (fait par le programme, pas l'agent).
    if (encours?.id === 'E1.1' && ditPret(e.text)) {
      await appeler($, H, 'avancer', { chantier: r.chantier, sous_etape: 'E1.1', etat: 'validee', citation: sansRappels(e.text).slice(0, 2000) })
      await rafraichir($, H)
    }
    return next(e)
  })

  // Un écran distant (Claude Desktop, téléphone) qui rejoint la session après l'ouverture du chantier : le volet
  // lui est rouvert, et le journal garde quelle surface est venue et si elle place les volets.
  on('session.attach', async ($, e, next) => {
    const res = await next(e)
    const r = await read($, rattachement)
    if (r && r.role === 'utilisateur') {
      const o = await $.ui.open({ id: PANE, title: `La boucle — ${r.chantier}` }).catch(err => ({ isPlaced: false, reason: String(err) }))
      await journal($, H, 'surface_attachee', { surface: e.surface, client: e.clientId, volet_a_cote: e.viewport?.isFullscreen ?? null, colonnes: e.viewport?.columns ?? null, place: o.isPlaced })
    }
    return res
  })

  on('turn.complete', async ($, e, next) => {
    const res = await next(e)
    const r = await read($, rattachement)
    if (!r || e.agentId !== undefined) return res
    const fin = await $.clock.now()
    await update($, derniereReponse, () => fin)
    const u = e.usage
    const config = await $.env.get('CLAUDE_CONFIG_DIR')
    await journal($, H, 'tour_termine', {
      compte: config ? (config.split(/[\\/]/).filter(Boolean).pop() ?? null) : '.claude',
      raison: e.reason,
      modele: u?.model ?? null,
      jetons_entree: u ? u.input_tokens : null,
      jetons_sortie: u ? u.output_tokens : null,
      jetons_cache_lus: u ? (u.cache_read_input_tokens ?? 0) : null,
      jetons_cache_ecrits: u ? (u.cache_creation_input_tokens ?? 0) : null,
    })
    await rafraichir($, H)
    return res
  })

  for (const o of OUTILS) {
    on('tool.call', { tool: `mcp__la-boucle-v2__${o.nom}` as never }, async ($, e) => {
      const r = await read($, rattachement)
      if (!r) return { deny: `Cette session n'est pas rattachée à un chantier de La boucle (${CMD} <chantier>).` }
      const { tool: _t, tool_use_id: _id, ...args } = e as unknown as Record<string, unknown>
      const rep = await appeler<Record<string, unknown>>($, H, o.commande, { ...args, chantier: r.chantier })
      if (!rep.ok) return { result: `Refusé : ${rep.refus}` }
      const v = await rafraichir($, H)
      if (o.commande === 'etat') return { result: v ? protocole(v, r.role) + `\n\nCe qui attend : ${v.attend?.quoi ?? 'rien'}` : 'État illisible.' }
      if (o.commande === 'lire') return { result: String(rep.resultat.contenu ?? '') }
      return { result: JSON.stringify(rep.resultat) + (v?.attend ? `\nCe qui attend maintenant : ${v.attend.quoi}.` : '') }
    })
  }

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const r = await read($, rattachement)
    if (!r) return next(e)
    const v = await read($, vue)
    const { Box, Text } = $.ui.resolve(e)
    const et = v?.etapes.find(x => x.n === v.etape_courante)
    return (
      <Box>
        <Text color="cyan">La boucle</Text>
        <Text dimColor>
          {' '}· {r.chantier}
          {et ? ` · étape ${et.n} ${et.titre}` : ''}
          {v?.attend ? ` · t'attend : ${v.attend.quoi}` : ''}
        </Text>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown, Link } = $.ui.resolve(e)
    const r = await read($, rattachement)
    const v = await read($, vue)
    const err = await read($, erreur)
    const deplies = await read($, deplie)
    const blocs = await read($, ouverts)
    const sv = await read($, suivi)
    const now = await $.clock.now()
    if (!r) return <Text dimColor>Aucun chantier rattaché à cette session ({CMD} &lt;chantier&gt;).</Text>
    if (!v) return <Text color={err ? 'red' : undefined} dimColor={!err}>{err ? `Programme injoignable : ${err}` : 'Lecture du chantier…'}</Text>
    const couleur = (etat: string) => (etat === 'en_cours' ? 'cyan' : etat === 'a_valider' ? 'yellow' : etat === 'validee' ? 'green' : etat === 'scellee' || etat === 'a_sceller' ? 'magenta' : undefined)
    const attendue = v.etapes.flatMap(x => x.sous_etapes).find(s => s.id === v.attend?.sous_etape)
    return (
      <Box flexDirection="column" gap={1} paddingX={1}>
        <Text bold>
          La boucle · {v.chantier}
          {v.categorie ? <Text dimColor> · {v.categorie.id}</Text> : null}
          {v.livre ? <Text color="green"> · livré</Text> : null}
          {err ? <Text color="red"> · relevé en retard</Text> : null}
        </Text>
        {v.attend ? (
          <Box key="attend" flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
            <Text>
              <Text bold color="yellow">À toi</Text> {v.attend.quoi}
            </Text>
            {attendue && attendue.id !== 'E1.1' ? (
              <Button key="aller" variant="primary" onPress={() => allerA($, attendue)}>
                Y aller
              </Button>
            ) : null}
          </Box>
        ) : (
          <Text color="green">Rien ne t'attend.</Text>
        )}
        {v.etapes.map(et => {
          // Une bascule inverse l'état par défaut (étape courante ouverte, les autres repliées) : l'étape courante se replie aussi.
          const ouverte = (et.n === v.etape_courante) !== deplies.includes(et.n)
          return (
            <Box key={`etape-${et.n}`} flexDirection="column">
              <Button
                key={`basculer-${et.n}`}
                plain
                onPress={() => update($, deplie, l => (l.includes(et.n) ? l.filter(n => n !== et.n) : [...l, et.n]))}
              >
                <Text bold={et.n === v.etape_courante} dimColor={et.etat === 'fermee'}>
                  {ouverte ? '▾' : '▸'} {et.n}. {et.titre}
                </Text>
                {et.etat === 'a_sceller' || et.etat === 'scellee' ? <Text color="magenta"> · {ETAT[et.etat]}</Text> : null}
              </Button>
              {ouverte && et.etat === 'a_sceller' && et.demande ? (
                <Box key={`demande-${et.n}`} flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1}>
                  <Text color="magenta" bold>À confirmer par le canal de confirmation</Text>
                  <Text dimColor>empreinte {String(et.demande.empreinte ?? '').slice(0, 12)}</Text>
                </Box>
              ) : null}
              {ouverte && et.etat === 'scellee' && et.scelle ? (
                <Box key={`scelle-${et.n}`} flexDirection="column" paddingLeft={2}>
                  <Button key={`scelle-fichier-${et.n}`} plain onPress={() => ouvrirFichier($, H, r.chantier, `etape${et.n}/scelle.json`)}>
                    <Text color="magenta">verrou · {heure(et.scelle.a)}</Text> <Text dimColor>↳ etape{et.n}/scelle.json</Text>
                  </Button>
                </Box>
              ) : null}
              {ouverte
                ? et.sous_etapes.map(s => (
                    <Box key={`se-${s.id}`} flexDirection="column" paddingLeft={2}>
                      {/* Volet épuré : une ligne par sous-étape ; un clic sur la ligne
                          déplie le résumé de la décision et « rouvrir ». Pas de messages bruts ni de noms de fichiers. */}
                      <Button key={`ligne-${s.id}`} plain onPress={() => basculer($, `se:${s.id}`)}>
                        <Text dimColor={s.etat === 'a_faire' || !!s.future}>
                          <Text color={couleur(s.etat)}>{REPERE[s.etat] ?? '○'}</Text> {s.titre}
                          {s.etat === 'a_valider' ? <Text color="yellow"> · à valider</Text> : null}
                          {s.qui !== 'moi' ? <Text dimColor> · {QUI[s.qui]}</Text> : null}
                          {s.points && s.etat !== 'a_faire' && s.points.tranches < s.points.total ? <Text dimColor> · {s.points.tranches}/{s.points.total}</Text> : null}
                        </Text>
                      </Button>
                      {blocs.includes(`se:${s.id}`) && !v.points[s.id] && (s.etat === 'validee' || s.decisions.length) ? (
                        <Box key={`detail-${s.id}`} flexDirection="column" paddingLeft={2}>
                          {s.decisions.length ? <Text dimColor>{resumeCourt(s.decisions[s.decisions.length - 1]?.resume ?? '')}</Text> : null}
                          {s.etat === 'validee' ? (
                            <Button key={`rouvrir-se-${s.id}`} plain onPress={() => rouvrirSousEtape($, s)}>
                              <Text color="cyan">rouvrir</Text>
                            </Button>
                          ) : null}
                        </Box>
                      ) : null}
                      {s.id === 'E1.2' && v.besoin ? (
                        <Box key="besoin" flexDirection="column" paddingLeft={2}>
                          <Button key="basculer-besoin" plain onPress={() => basculer($, 'besoin')}>
                            <Text dimColor>{blocs.includes('besoin') ? '▾' : '▸'} le besoin rédigé</Text>
                          </Button>
                          {blocs.includes('besoin') ? <Markdown text={v.besoin} /> : null}
                        </Box>
                      ) : null}
                      {s.id === 'E1.3.1' && v.catalogue ? (
                        <Box key="catalogue" flexDirection="column" paddingLeft={2}>
                          <Text bold>
                            Catalogue de l'outil : {v.catalogue.actions} actions, {v.catalogue.ecrans.length} écrans
                          </Text>
                          {v.catalogue.ecrans.map(ec => (
                            <Box key={`ecran-${ec.ecran}`} flexDirection="column">
                              <Button key={`ecran-${ec.ecran}`} plain onPress={() => basculer($, `ecran:${ec.ecran}`)}>
                                {blocs.includes(`ecran:${ec.ecran}`) ? '▾' : '▸'} {ec.ecran} <Text dimColor>· {ec.actions.length} actions</Text>
                              </Button>
                              {blocs.includes(`ecran:${ec.ecran}`)
                                ? ec.actions.map(ac => (
                                    <Text>
                                      {'    '}
                                      {ac.action}
                                      {ac.description ? <Text dimColor> — {ac.description}</Text> : null}
                                    </Text>
                                  ))
                                : null}
                            </Box>
                          ))}
                        </Box>
                      ) : null}
                      {v.points[s.id] && (s.etat === 'en_cours' || s.etat === 'a_valider' || blocs.includes(`se:${s.id}`)) ? (
                        <Box key={`points-${s.id}`} flexDirection="column" paddingLeft={2}>
                          {(v.points[s.id] ?? []).map(p => {
                            const d = [...s.decisions].reverse().find(x => x.point === p.id)
                            const tranche = d && d.statut !== 'rouvert'
                            const deplie = tranche && blocs.includes(`pt:${p.id}`)
                            return (
                              <Box key={`point-${p.id}`} flexDirection="column">
                                <Button key={`ligne-${p.id}`} plain onPress={() => basculer($, `pt:${p.id}`)}>
                                  <Text dimColor={!tranche}>
                                    <Text color={tranche ? 'green' : undefined}>{tranche ? '✓' : '○'}</Text> {p.titre}
                                  </Text>
                                </Button>
                                {deplie ? (
                                  <Box key={`detail-${p.id}`} flexDirection="column" paddingLeft={2}>
                                    <Text dimColor>{d.resume}</Text>
                                    <Button key={`rouvrir-${p.id}`} plain onPress={() => rouvrirPoint($, s.id, p.id, p.titre)}>
                                      <Text color="cyan">rouvrir</Text>
                                    </Button>
                                  </Box>
                                ) : null}
                              </Box>
                            )
                          })}
                        </Box>
                      ) : null}
                      {s.id === 'E1.5' && v.arbre.termes.length ? (
                        <Box key="arbre" flexDirection="column" paddingLeft={2}>
                          <Text bold>Arbre des définitions</Text>
                          {v.arbre.termes.map(t => (
                            <Text>
                              {'  '.repeat(t.couche)}
                              {t.id} {t.libelle} <Text color={t.etat === 'modele' ? 'yellow' : t.etat === 'liste' ? 'green' : 'cyan'}>[{ETAT_TERME[t.etat]}]</Text>
                              {t.liste ? <Text dimColor> {t.liste.slice(0, 6).join(', ')}{t.liste.length > 6 ? ` … (${t.liste.length})` : ''}</Text> : null}
                            </Text>
                          ))}
                          {Object.entries(v.arbre.seuils).map(([n, b]) => (
                            <Text dimColor>
                              {'  '}seuils de la couche racine : B1 {b.b1 == null ? 'à fixer' : String(b.b1)} · B2 {b.b2 == null ? 'à fixer' : String(b.b2)} (proposés)
                            </Text>
                          ))}
                        </Box>
                      ) : null}
                      {s.id === 'E1.7' && v.relecture.length ? (
                        <Box key="relecture" flexDirection="column" paddingLeft={2}>
                          {v.relecture.map(r => (
                            <Box key={`passe-${r.passe}`} flexDirection="column">
                              <Text bold>
                                Passe {r.passe} ({r.relecteurs.join(' et ')}, {r.exemples} exemples) : {r.desaccords} désaccord{r.desaccords > 1 ? 's' : ''}
                              </Text>
                              {Object.entries(r.par_critere).map(([k, c]) => (
                                <Text color={c.garde ? 'green' : 'yellow'}>
                                  {'  '}
                                  {k} : accord {pct(c.accord)} {c.garde ? '· gardé' : '· à préciser'}
                                </Text>
                              ))}
                            </Box>
                          ))}
                        </Box>
                      ) : null}
                      {(sv?.agents ?? [])
                        .filter(a => a.sous_etape === s.id && a.etat !== 'arrete')
                        .map(a => (
                          <Text color={enRouge(a, now) ? 'red' : a.etat === 'fini' ? 'green' : undefined} dimColor={a.etat === 'fini'}>
                            {'  '}
                            {a.genre === 'programme' ? 'programme' : 'agent'} {a.role ?? a.nom} · {a.etat === 'fini' ? 'fini' : enRouge(a, now) ? 'bloqué ou en panne' : `depuis ${depuisQuand(a.depuis, now)}`}
                            {a.action || a.ou_en_est ? ` · ${a.action ?? a.ou_en_est}` : ''}
                          </Text>
                        ))}
                      {s.id === 'E2.14' && v.calcul ? (
                        <Box key="calcul" flexDirection="column" paddingLeft={2}>
                          <Text bold>
                            Calcul {v.calcul.facon === 'prudent' ? 'prudent' : 'au plus juste'} : {v.calcul.total} données en tout
                          </Text>
                          {['entrainement', 'selection', 'pre_evaluation', 'examen', 'verification'].map(lot => (
                            <Text>
                              {'  '}
                              {LOTS[lot]} : {v.calcul!.tailles[lot]}
                              {v.calcul!.fixe_par[lot] && v.calcul!.fixe_par[lot] !== 'la sortie (N1)' ? <Text dimColor> (fixé par {v.calcul!.fixe_par[lot]})</Text> : null}
                            </Text>
                          ))}
                          {Object.entries(v.calcul.portes_par_critere ?? {}).map(([id, x]) => (
                            <Text key={id}>
                              {'  '}
                              {x.libelle} : {x.filtre ? 'filtres 1 et 2' : 'porte 1'} {pct(x.porte1)}
                              {x.filtre ? '' : ` · porte 2 ${pct(x.porte2)}`} · porte 3 {x.lots.examen.texte}
                            </Text>
                          ))}
                          <Text dimColor>
                            {'  '}
                            {v.calcul.filtres
                              ? `au niveau visé : livré ${Math.round((v.calcul.chance_livraison_au_vise ?? 0) * 100)} sur 100, filtre 1 franchi ${Math.round(v.calcul.filtres.chance_au_vise.selection * 100)} sur 100, filtre 2 ${Math.round(v.calcul.filtres.chance_au_vise.pre_evaluation * 100)} sur 100 · `
                              : ''}
                            chance d'être reçu au niveau visé : {Math.round((v.calcul.chance_au_vise ?? 0) * 100)} sur 100 · chaque sortie au-dessus de sa barre :{' '}
                            {(v.calcul.courbe_chance_recu ?? [])
                              .filter(p => Math.round(p.decalage * 100) % 2 === 0)
                              .slice(-5)
                              .map(p => `+${Math.round(p.decalage * 100)} pts → ${Math.round(p.chance * 100)} sur 100`)
                              .join(' · ')}
                          </Text>
                          {v.calcul.motifs_compromis.map(m => (
                            <Text color="yellow">{'  '}compromis à trancher : {m}</Text>
                          ))}
                          {(v.calcul.a_confirmer ?? []).map(m => (
                            <Text dimColor>{'  '}étiquettes : {m}</Text>
                          ))}
                        </Box>
                      ) : null}
                      {s.id === 'E3.1' && v.fabrication ? (
                        <Box key="fabrication" flexDirection="column" paddingLeft={2}>
                          {v.fabrication.phases.map(ph => (
                            <Text color={ph.etat === 'panne' ? 'red' : ph.etat === 'fini' ? 'green' : undefined}>
                              {'  '}
                              {ph.nom} · {ph.etat}
                              {ph.comptes ? <Text dimColor> · {Object.entries(ph.comptes).map(([k, n]) => `${k} ${n}`).join(' · ')}</Text> : null}
                            </Text>
                          ))}
                          <Text color={v.fabrication.depasse ? 'red' : undefined}>
                            {'  '}coût réel {v.fabrication.cout_eur.toFixed(2)} €{v.fabrication.devis_eur != null ? ` pour un devis de ${v.fabrication.devis_eur.toFixed(2)} €` : ''}
                            {v.fabrication.depasse ? ' · dépassement : la fabrication s’arrête et revient vers toi' : ''}
                          </Text>
                          {v.fabrication.fermee ? <Text color="red">{'  '}fabrication fermée : {v.fabrication.fermee}</Text> : null}
                        </Box>
                      ) : null}
                      {s.id === 'E5.6' && v.usage ? (
                        <Box key="usage" flexDirection="column" paddingLeft={2}>
                          <Text>
                            {'  '}
                            {v.usage.arrivees} consignes réelles reçues · {v.usage.scellees} scellées dès l'arrivée ({v.usage.etiquetees} étiquetées, il en faut {v.usage.scellee_min}) · {v.usage.sonde} pour la sonde
                          </Text>
                          <Text dimColor>
                            {'  '}jugements sur la part scellée : {v.usage.consultations} sur {v.usage.consultations_max}
                            {v.usage.consultations >= v.usage.consultations_max ? ' · part usée : à renouveler' : ''}
                          </Text>
                          {v.usage.jugements.map((j, i) => (
                            <Text key={`usage-j-${i}`} color={j.verdict === 'adoptee' ? 'green' : j.verdict === 'refusee' ? 'red' : undefined}>
                              {'  '}
                              {j.modification} → {j.verdict.replace('_', ' ')} : {j.pourquoi}
                            </Text>
                          ))}
                        </Box>
                      ) : null}
                      {s.id === 'E3.2' && v.relecture_banc ? (
                        <Box key="relecture-banc" flexDirection="column" paddingLeft={2}>
                          <Text color={v.relecture_banc.depasse ? 'red' : undefined}>
                            {'  '}
                            {v.relecture_banc.relues} relues sur {v.relecture_banc.a_relire} · {v.relecture_banc.erreurs} erreur{v.relecture_banc.erreurs > 1 ? 's' : ''} · erreur maximale prouvée{' '}
                            {v.relecture_banc.borne == null ? 'non mesurée' : pct(v.relecture_banc.borne)}
                            {v.relecture_banc.tolerance != null ? ` (tolérance ${pct(Number(v.relecture_banc.tolerance))})` : ''}
                          </Text>
                          {v.confirmation_portes ? (
                            <Text color={v.confirmation_portes.etat === 'ecart' ? 'red' : v.confirmation_portes.etat === 'figees' ? 'green' : undefined}>
                              {'  '}
                              {v.confirmation_portes.motif}
                            </Text>
                          ) : null}
                          {v.relecture_banc.restantes.length ? (
                            <Button key="ouvrir-relecture" plain onPress={() => ouvrirRelecture($, H, r.chantier)}>
                              {'  '}↳ ouvrir la vue de relecture
                            </Button>
                          ) : null}
                        </Box>
                      ) : null}
                      {s.etat === 'a_faire'
                        ? null
                        : s.sorties
                            .filter(o => o.existe && o.chemin.endsWith('.md') && !(s.id === 'E1.2' && v.besoin))
                            .map((o, i) => (
                              <Button key={`ouvrir-${s.id}-${i}`} plain onPress={() => ouvrirFichier($, H, r.chantier, o.chemin)}>
                                <Text dimColor>
                                  {'    '}▸ {nomDocument(o.chemin)}
                                </Text>
                              </Button>
                            ))}
                    </Box>
                  ))
                : null}
            </Box>
          )
        })}
        {v.boucle ? (
          <Box key="tableau-boucle" flexDirection="column">
            <Text bold>
              Essais{v.boucle.mis_a_jour.essais ? <Text dimColor> · {heure(v.boucle.mis_a_jour.essais.a)}</Text> : null}
              {v.boucle.mis_a_jour.essais?.fige ? <Text color="red"> · figé depuis {heure(v.boucle.mis_a_jour.essais.a)}</Text> : null}
            </Text>
            <Box flexDirection="row" flexWrap="wrap" gap={1}>
              {Object.entries(v.boucle.strategies).map(([sid, st]) => (
                <Box key={`strat-${sid}`} borderStyle="round" borderColor={st.etat === 'active' ? 'cyan' : 'gray'} paddingX={1} flexDirection="column">
                  <Text bold>{st.nom ?? sid}</Text>
                  <Text dimColor>
                    {st.etat ?? 'non mesuré'} · {st.essais ?? 0} essais
                  </Text>
                  <Text dimColor>
                    indice {st.indice == null ? '—' : pct(st.indice)} · chances {st.chances == null ? '—' : pct(st.chances)}
                  </Text>
                </Box>
              ))}
            </Box>
            <Text bold>
              {'n°  stratégie  '}
              {v.boucle.colonnes.map(c => `${c}${v.boucle!.minimums[c] != null ? ` (min ${pct(Number(v.boucle!.minimums[c]))})` : ''}`).join('  ')}
              {'  vitesse  verdict'}
            </Text>
            {v.boucle.essais.slice(-15).map(es => (
              <Text bold={es.verdict === 'champion'} dimColor={v.boucle!.strategies[es.strategie]?.etat === 'fermee'}>
                {es.verdict === 'champion' ? '★ ' : '  '}
                {String(es.essai).padEnd(3)} {String(es.strategie).padEnd(10)}{' '}
                {v.boucle!.colonnes.map(c => {
                  const x = es.scores?.[c]
                  const mini = v.boucle!.minimums[c]
                  return (
                    <Text color={x != null && mini != null && x >= Number(mini) ? 'green' : undefined}>
                      {x == null ? 'non mesuré' : `${es.partiel ? '≈' : ''}${pct(x)}`}{'  '}
                    </Text>
                  )
                })}
                {es.vitesse_s != null ? `${es.vitesse_s} s` : 'non mesuré'} {es.verdict === 'arrete_tot' ? 'arrêté tôt' : es.verdict === 'rejete' ? 'rejeté' : es.verdict ?? ''}
                {es.promu && es.verdict !== 'champion' ? ' · promu' : ''}
              </Text>
            ))}
            {v.boucle.essais.length > 15 ? <Text dimColor>{v.boucle.essais.length - 15} essais plus anciens (journal des essais)</Text> : null}
            {v.boucle.bibliotheque ? (
              <Text key="bibliotheque" dimColor>
                Bibliothèque : {v.boucle.bibliotheque.etablies_ici} leçon(s) établie(s) ici · {v.boucle.bibliotheque.a_reverifier} à revérifier sur ce banc · {v.boucle.bibliotheque.pistes} piste(s) non prouvée(s) · {v.boucle.bibliotheque.harnais} harnais gardé(s)
              </Text>
            ) : null}
            {(v.boucle.audits ?? []).map(x => (
              <Text key={`audit-${x.porte}`} color={x.passe ? undefined : 'red'} dimColor={x.passe}>
                Audit avant la porte {x.porte}{x.version ? ` (${x.version})` : ''} : {x.passe ? 'passé' : `porte fermée — ${x.echecs.map(e => `${e.id} : ${e.preuve}`).join(' ; ')}`}
              </Text>
            ))}
            {(v.boucle.depense ?? [])
              .filter(x => !x.illisible)
              .map(x => (
                <Text key={`depense-${x.lignee}`} dimColor>
                  Dépense de la lignée {x.lignee} : {x.sessions_recherche ?? 0} sessions de recherche · {x.mesures ?? 0} mesures · {(x.appels ?? 0).toLocaleString('fr-FR')} appels au petit modèle
                  {x.plafond?.sessions_recherche ? ` · plafond ${x.plafond.sessions_recherche} sessions` : ''}
                  {x.plafond?.mesures ? ` · plafond ${x.plafond.mesures} mesures` : ''}
                </Text>
              ))}
            {v.boucle.machines ? (
              <Box key="machines" flexDirection="column">
                <Text bold>
                  Machines <Text dimColor>· {(v.boucle.machines.mesures ?? []).filter(m => m.etat !== 'fini').length} mesure(s) en cours</Text>
                  {v.boucle.mis_a_jour.machines?.fige ? <Text color="red"> · figé depuis {heure(v.boucle.mis_a_jour.machines.a)}</Text> : null}
                </Text>
                {(v.boucle.machines.mesures ?? [])
                  .filter(m => m.etat !== 'fini')
                  .map(m => (
                    <Text>
                      {'  '}essai {String(m.essai)}
                      {m.strategie ? ` (${m.strategie})` : ''} : {m.faites ?? 'non mesuré'} / {m.total ?? 'non mesuré'}
                    </Text>
                  ))}
                {(v.boucle.machines.machines ?? []).map(mc => (
                  <Text color={mc.activite === 'hors ligne' ? 'red' : undefined}>
                    {'  '}
                    {mc.nom}
                    {mc.carte ? ` · ${mc.carte}` : ''} · {mc.activite ?? 'non mesuré'} · {mc.donnees ?? 'non mesuré'} données · {mc.vitesse != null ? `${mc.vitesse}/min` : 'non mesuré'} ·{' '}
                    {mc.puissance_w != null ? `${mc.puissance_w} W` : 'non mesuré'} · {mc.cout_eur != null ? `${mc.cout_eur.toFixed(2)} €` : 'non mesuré'}
                  </Text>
                ))}
                {v.boucle.machines.total ? (
                  <Text bold>
                    {'  '}toutes les machines : {v.boucle.machines.total.donnees ?? 'non mesuré'} données · {v.boucle.machines.total.vitesse != null ? `${v.boucle.machines.total.vitesse}/min` : 'non mesuré'}
                    {v.boucle.machines.total.minutes_par_mesure != null ? ` · ${v.boucle.machines.total.minutes_par_mesure} min par mesure` : ''}
                  </Text>
                ) : null}
              </Box>
            ) : null}
            <Box key="journal-essais" flexDirection="column">
              <Text bold>Journal des essais</Text>
              {Object.entries(v.boucle.strategies)
                .reverse()
                .map(([sid, st]) => {
                  const cle = `strat:${sid}`
                  const ouvert = st.etat === 'active' ? !blocs.includes(cle) : blocs.includes(cle)
                  return (
                    <Box key={`journal-${sid}`} flexDirection="column">
                      <Button key={cle} plain onPress={() => basculer($, cle)}>
                        {ouvert ? '▾' : '▸'} {st.nom ?? sid} — {st.idee ?? 'idée non écrite'} <Text dimColor>· {st.etat ?? ''} · {st.essais ?? 0} essais</Text>
                      </Button>
                      {ouvert && st.raison ? <Text color="yellow">{'    '}{st.raison}</Text> : null}
                      {ouvert
                        ? v.boucle!.essais
                            .filter(es => es.strategie === sid)
                            .reverse()
                            .map(es => (
                              <Box key={`es-${sid}-${String(es.essai)}`} flexDirection="column">
                                <Button key={`detail-${String(es.essai)}`} plain onPress={() => basculer($, `essai:${String(es.essai)}`)}>
                                  {'    '}
                                  {String(es.essai)} · {es.resume ?? 'résumé manquant'} <Text dimColor>· {es.verdict ?? ''}</Text>
                                </Button>
                                {blocs.includes(`essai:${String(es.essai)}`) && es.detail ? <Text dimColor>{'      '}{String(es.detail)}</Text> : null}
                                {blocs.includes(`essai:${String(es.essai)}`) && Array.isArray(es.attribution)
                                  ? es.attribution.map((a, i) => (
                                      <Text key={`att-${String(es.essai)}-${i}`} dimColor>
                                        {'      '}
                                        {a.dimension && a.dimension !== 'unique' ? `${a.dimension} · ` : ''}
                                        {a.changement ?? 'modification'} → {a.verdict === 'nui' ? 'a nui' : a.verdict === 'aide' ? 'a aidé' : a.verdict}
                                      </Text>
                                    ))
                                  : null}
                              </Box>
                            ))
                        : null}
                    </Box>
                  )
                })}
            </Box>
            {v.boucle.controle.length ? (
              <Box key="controle" flexDirection="column">
                <Text color="red" bold>Vérification du tableau : {v.boucle.controle.length} problème(s)</Text>
                {v.boucle.controle.slice(0, 8).map(pb => (
                  <Text color="red">
                    {'  '}
                    {pb.section} : {pb.quoi}
                  </Text>
                ))}
              </Box>
            ) : null}
          </Box>
        ) : null}
        {sv && sv.agents.length ? (
          <Box key="agents" flexDirection="column">
            <Text bold>Agents</Text>
            {sv.agents
              .filter(a => a.etat !== 'arrete' && (a.etat !== 'fini' || blocs.includes('agents-finis')))
              .map(a => (
                <Box key={`agent-${a.nom}`} flexDirection="column" borderStyle="round" borderColor={enRouge(a, now) ? 'red' : a.etat === 'fini' ? 'green' : 'gray'} paddingX={1}>
                  <Text bold>
                    {a.role ?? a.nom} <Text dimColor>· {a.nom}</Text>
                  </Text>
                  <Text dimColor>
                    {a.sous_etape ? `${a.sous_etape} · ` : ''}
                    {a.quoi ?? ''} · depuis {depuisQuand(a.depuis, now)}
                    {a.compte ? ` · compte ${a.compte}` : ''}
                    {a.ou ? ` · ${a.ou}` : ''}
                  </Text>
                  {a.action || a.ou_en_est ? <Text>{a.action ?? a.ou_en_est}</Text> : null}
                  {enRouge(a, now) ? <Text color="red">Bloqué ou en panne{a.relances ? ` · relancé ${a.relances} fois` : ''}</Text> : null}
                  {a.choix_compte?.ecartes_orange?.length ? <Text color="yellow">parti sur {a.compte} : {a.choix_compte.ecartes_orange.join(', ')} proche de sa limite</Text> : null}
                  <Box>
                    {a.lien ? (
                      <Link key={`lien-${a.nom}`} href={a.lien}>
                        Ouvrir sa conversation
                      </Link>
                    ) : null}
                    {a.etat === 'travaille' || a.etat === 'attend' || a.etat === 'panne' ? (
                      <Button key={`arreter-${a.nom}`} plain onPress={() => arreterAgent($, H, r.chantier, a.nom)}>
                        {' '}[arrêter]
                      </Button>
                    ) : null}
                  </Box>
                </Box>
              ))}
            {sv.agents.some(a => a.etat === 'fini') ? (
              <Button key="agents-finis" plain onPress={() => basculer($, 'agents-finis')}>
                {blocs.includes('agents-finis') ? 'masquer' : 'voir'} les travaux finis ({sv.agents.filter(a => a.etat === 'fini').length})
              </Button>
            ) : null}
          </Box>
        ) : null}
        {sv ? (
          <Box key="moteur" flexDirection="column">
            <Text bold>
              Moteur <Text dimColor>· comptes Claude des agents{sv.comptes.comptes.length === 0 ? ' · aucun branché' : ''}</Text>
            </Text>
            {sv.comptes.comptes.map(c => (
              <Box key={`compte-${c.id}`}>
                <Text color={c.orange ? 'yellow' : undefined}>
                  {'  '}
                  {c.nom} : 5 h {c.h5 == null ? 'non mesuré' : `${c.h5} %`} · semaine {c.semaine == null ? 'non mesuré' : `${c.semaine} %`}
                  {c.orange ? ' · proche de sa limite' : ''}
                  <Text dimColor> · {c.agents.length ? c.agents.join(', ') : 'aucun agent'}</Text>
                </Text>
                <Button key={`debrancher-${c.id}`} plain onPress={() => brancher($, H, r.chantier, c.id, 'debrancher')}>
                  {' '}[débrancher]
                </Button>
              </Box>
            ))}
            {(sv.comptes.connus ?? []).length ? (
              <Box key="brancher" flexDirection="row" flexWrap="wrap">
                <Text dimColor>{'  '}brancher :</Text>
                {(sv.comptes.connus ?? []).map(c => (
                  <Button key={`brancher-${c.id}`} plain onPress={() => brancher($, H, r.chantier, c.id, 'brancher')}>
                    {' '}[{c.nom}]
                  </Button>
                ))}
              </Box>
            ) : null}
            {sv.comptes.sans_releve.length ? <Text dimColor>{'  '}sans relevé : {sv.comptes.sans_releve.join(', ')}</Text> : null}
            {sv.comptes.erreur ? <Text color="red">{'  '}relevé des comptes injoignable</Text> : null}
          </Box>
        ) : null}
        {sv && sv.budget.passes.length ? (
          <Box key="budget" flexDirection="column">
            <Text bold>
              Budget : prévu {sv.budget.prevu_eur.toFixed(2)} € · validé {sv.budget.valide_eur.toFixed(2)} € · dépensé {sv.budget.depense_eur.toFixed(2)} €
            </Text>
            {sv.budget.passes.map(p => (
              <Text color={p.arretee ? 'red' : p.accord ? undefined : 'yellow'} dimColor={!!p.accord && !p.arretee}>
                {'  '}
                {p.role ?? p.id} ({p.fournisseur} {p.modele}) : {(p.cout_estime_eur ?? 0).toFixed(2)} € estimé
                {p.accord ? ` · accepté ${(p.montant_accepte_eur ?? 0).toFixed(2)} €` : ' · attend ton accord'}
                {p.depense_eur ? ` · dépensé ${p.depense_eur.toFixed(2)} €` : ''}
                {p.arretee ? ' · arrêtée : dépassement' : ''}
              </Text>
            ))}
          </Box>
        ) : null}
        {v.lexique.length ? (
          <Box key="lexique" flexDirection="column">
            <Button key="lexique" plain onPress={() => basculer($, 'lexique')}>
              {blocs.includes('lexique') ? '▾' : '▸'} Lexique <Text dimColor>· {v.lexique.length}</Text>
            </Button>
            {blocs.includes('lexique')
              ? v.lexique.map(l => (
                  <Text>
                    {'  '}
                    {l.notion} <Text dimColor>— « {l.citation.slice(0, 80)} »</Text>
                  </Text>
                ))
              : null}
          </Box>
        ) : null}
        <Box key="mesures" flexDirection="column">
          <Button key="mesures" plain onPress={() => basculer($, 'mesures')}>
            {blocs.includes('mesures') ? '▾' : '▸'} Mesures
          </Button>
          {blocs.includes('mesures')
            ? v.etapes.flatMap(et => {
                const me = v.mesures.etapes[String(et.n)]
                if (!me) return []
                return [
                  <Text bold>
                    {'  '}étape {et.n} · {duree(me.duree_s)} · toi {duree(me.attente_utilisateur_s)} · jetons {jetons(me.jetons_entree)} / {jetons(me.jetons_sortie)}
                  </Text>,
                  ...et.sous_etapes
                    .filter(se => v.mesures.sous_etapes[se.id])
                    .map(se => {
                      const x = v.mesures.sous_etapes[se.id]!
                      return (
                        <Text dimColor>
                          {'    '}
                          {se.titre} · {duree(x.duree_s)}
                          {x.en_cours ? ' (en cours)' : ''} · {x.echanges} échange{x.echanges > 1 ? 's' : ''} · réponse {duree(x.temps_reponse_median_s)}
                          {x.part_autre_chose ? ` · « autre chose » ${Math.round(x.part_autre_chose * 100)} %` : ''}
                          {x.reouvertures ? ` · rouverte ${x.reouvertures} fois` : ''}
                          {x.incidents ? ` · ${x.incidents} incident(s)` : ''}
                        </Text>
                      )
                    }),
                ]
              })
            : null}
          {blocs.includes('mesures')
            ? Object.entries(v.mesures.comptes).map(([compte, j]) => (
                <Text dimColor>
                  {'  '}compte {compte} · {j.tours} tours · jetons {jetons(j.jetons_entree)} / {jetons(j.jetons_sortie)}
                </Text>
              ))
            : null}
          {blocs.includes('mesures') ? <Text dimColor>{'  '}non mesuré : {v.mesures.non_mesure.join(' ; ')}</Text> : null}
        </Box>
        {Object.keys(v.registre).length ? (
          <Box key="registre" flexDirection="column">
            <Button key="registre" plain onPress={() => basculer($, 'registre')}>
              {blocs.includes('registre') ? '▾' : '▸'} Règles <Text dimColor>· {Object.keys(v.registre).length}</Text>
            </Button>
            {blocs.includes('registre')
              ? Object.entries(v.registre).map(([k, r]) => (
                  <Text>
                    {'  '}
                    {r.libelle ?? k} : {JSON.stringify(r.valeur)} <Text color={r.statut === 'scelle' ? 'magenta' : 'yellow'}>[{r.statut === 'propose' ? 'proposé' : r.statut === 'scelle' ? 'scellé' : 'fixé'}]</Text>
                  </Text>
                ))
              : null}
          </Box>
        ) : null}
      </Box>
    )
  })

  // E3.2 : la vue de relecture, une donnée à la fois avec sa bonne réponse. Ce qu'elle montre ne passe jamais par
  // l'agent : le volet lit le programme directement, l'agent ne reçoit que des comptes.
  on('ui.render', { component: 'Pane', requestId: PANE_RELECTURE }, async ($, e) => {
    const r = await read($, rattachement)
    const d = await read($, donneeRelue)
    const v = await read($, vue)
    if (e.surface === 'mobile') {
      const { Text } = $.ui.resolve(e)
      return <Text dimColor>La relecture se fait sur l'ordi (champ de correction).</Text>
    }
    const { Box, Text, Button, Input } = $.ui.resolve(e)
    if (!r) return <Text dimColor>Aucun chantier rattaché.</Text>
    if (!d) return <Text color="green">Rien à relire : toutes les données prévues sont relues.</Text>
    const montrer = (x: unknown) => (typeof x === 'string' ? x : JSON.stringify(x, null, 2))
    return (
      <Box flexDirection="column" gap={1} paddingX={1}>
        <Text dimColor>
          {d.lot ? `lot ${d.lot} · ` : ''}donnée {d.id}
          {v?.relecture_banc ? ` · ${v.relecture_banc.relues} relues sur ${v.relecture_banc.a_relire}` : ''}
        </Text>
        <Text>{montrer(d.donnee)}</Text>
        <Text bold>Bonne réponse : {montrer(d.reponse)}</Text>
        <Button key="juste" variant="primary" onPress={() => noterRelecture($, H, r.chantier, d.id, 'ok')}>
          Juste
        </Button>
        <Input key="correction" label="Corriger (la bonne réponse)" placeholder="ex. FAIRE_REPETER" onSubmit={value => noterRelecture($, H, r.chantier, d.id, 'corrige', value)} />
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE_FICHIER }, async ($, e) => {
    const { Box, Text, Markdown, Code } = $.ui.resolve(e)
    const f = await read($, fichier)
    if (!f) return <Text dimColor>Aucun fichier ouvert.</Text>
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text dimColor>{f.chemin}</Text>
        {f.chemin.endsWith('.md') ? <Markdown text={f.contenu} /> : <Code language={f.chemin.endsWith('.json') ? 'json' : 'text'} source={f.contenu} />}
      </Box>
    )
  })
}
