// Contrat du mod la-boucle-v2 : ce que le volet et la bande lisent, et la forme des réponses du programme.

export type EtatSousEtape = 'a_faire' | 'en_cours' | 'a_valider' | 'validee' | 'scellee'

export type Decision = {
  a: string
  sous_etape?: string
  point?: string | null
  resume: string
  citation: string
  option?: string | null
  statut?: string
}

export type Sortie = { chemin: string; absolu: string; existe: boolean }

export type SousEtape = {
  id: string
  titre: string
  qui: 'moi' | 'agent' | 'programme'
  etat: EtatSousEtape
  depuis?: string | null
  valide_le?: string | null
  citation?: string | null
  entree?: string
  consigne?: string
  sorties: Sortie[]
  decisions: Decision[]
  points: { tranches: number; total: number } | null
  notion: boolean
  /** Sous-étape décrite pour plus tard : ne s'ouvre pas, ne bloque rien. */
  future?: boolean
}

export type Etape = {
  n: number
  titre: string
  resume: string
  tu_decides: string
  etat: 'ouverte' | 'fermee' | 'a_sceller' | 'scellee'
  scelle?: { a: string; empreinte?: string; documents: { chemin: string; empreinte: string }[] } | null
  demande?: { a: string | null; empreinte: string | null; documents: number } | null
  sous_etapes: SousEtape[]
}

export type Terme = {
  id: string
  libelle: string
  definition?: string | null
  couche: number
  parent: string | null
  etat: 'a_definir' | 'redecoupe' | 'liste' | 'modele'
  liste: string[] | null
  citation: string | null
  a?: string
  historique?: unknown[]
}

export type Mesure = {
  duree_s: number | null
  attente_utilisateur_s: number | null
  echanges: number
  decisions: number
  autre_chose: number
  reouvertures: number
  jetons_entree: number | null
  jetons_sortie: number | null
  tours: number
  incidents: number
  temps_reponse_median_s?: number | null
  part_autre_chose?: number | null
  raisons_reouverture?: (string | null)[]
  en_cours?: boolean
}

export type Mesures = {
  sous_etapes: Record<string, Mesure>
  etapes: Record<string, Mesure>
  evenements: number
  autres: number
  comptes: Record<string, { jetons_entree: number; jetons_sortie: number; tours: number }>
  non_mesure: string[]
}

export type Agent = {
  nom: string
  role?: string | null
  sous_etape?: string | null
  quoi?: string | null
  compte?: string | null
  ou?: string | null
  genre?: 'agent' | 'programme' | null
  etat: 'travaille' | 'attend' | 'fini' | 'panne' | 'arrete'
  depuis: string
  maj?: string | null
  ou_en_est?: string | null
  etat_session?: string | null
  action?: string | null
  activite?: string | null
  lien?: string | null
  relances?: number | null
  choix_compte?: { compte: string; raison: string; ecartes_orange?: string[]; orange?: boolean }
  bloque?: boolean
  relancable?: boolean
  relance?: string[] | null | null
  [autre: string]: unknown
}

export type Passe = {
  id: string
  role?: string | null
  fournisseur?: string | null
  modele?: string | null
  cout_estime_eur?: number | null
  montant_accepte_eur?: number | null
  depense_eur?: number | null
  quota_pct?: number | null
  accord?: { citation: string; a: string } | null
  arretee?: unknown | null
  [autre: string]: unknown
}

export type Suivi = {
  agents: Agent[]
  comptes: { branches: string[]; comptes: { id: string; nom: string; h5: number | null; semaine: number | null; orange: boolean; agents: string[] }[]; sans_releve: string[]; erreur?: string | null; connus?: { id: string; nom: string }[] }
  budget: { prevu_eur: number; valide_eur: number; depense_eur: number; quota_prevu_pct: number; quota_valide_pct: number; passes: Passe[] }
}

export type LotPorte = { n: number; k: number; rates_max: number; seuil: number | null; texte: string }

export type PorteCritere = {
  libelle: string
  genre: 'justesse' | 'plafond' | 'b1'
  compte_sur: string
  barre: number
  vise: number
  barre_testee: number
  porte1: number
  porte2: number
  niveau_predit: number
  filtre?: boolean
  porte3: Record<'examen' | 'verification', number | null>
  lots: Record<'selection' | 'pre_evaluation' | 'examen' | 'verification', LotPorte>
  [autre: string]: unknown
}

export type Calcul = {
  a: string
  facon: 'prudent' | 'juste'
  tailles: Record<string, number>
  n_par_sortie: Record<string, Record<string, number>>
  total: number
  fixe_par: Record<string, string>
  portes_par_critere: Record<string, PorteCritere>
  chance_au_vise: number
  portes_filtres?: boolean
  chance_livraison_au_vise?: number
  filtres?: { cible_au_vise: number; plafond_a_la_barre: number; chance_au_vise: Record<'selection' | 'pre_evaluation', number>; chance_a_la_barre: Record<string, Record<string, number>>; examen_livraison_seule: Record<string, number> | null; regle: string } | null
  courbe_chance_recu: { decalage: number; sorties: Record<string, number>; chance: number; chance_livraison: number }[]
  motifs_compromis: string[]
  etiquettes?: { borne_mesuree: number | null; borne_prevue: number | null; relues_pilote: number | null; erreurs_pilote: number | null; plan: { relectures_sans_erreur: number; relectures_selon_erreurs: Record<string, number> } | null; a_confirmer: boolean; pilote_contredit_tolerance: boolean; motif: string | null; regle: string | null; inversions_vers_executer?: { tolerance: number; relectures: number; permises: number; strates: string[]; borne_a_zero: number; borne_au_dela: number; texte: string; regle: string } | null }
  a_confirmer?: string[]
  entrainement?: { minimum_hors_selection: number | null; hors_selection: Record<string, number>; total_hors_selection: number; selection: Record<string, number>; regle: string }
  tableaux?: { tailles: string; seuils: string; profils: string; facons: string | null }
  [autre: string]: unknown
}

export type ConfirmationPortes = { etat: 'en_attente' | 'figees' | 'ecart'; motif: string; borne_prevue: number; borne_mesuree?: number; relectures_plan: number; erreurs_permises: number; relues: number; erreurs: number; inversions_vers_executer?: number; inversions_permises?: number; a?: string; chance_livraison_au_vise?: number; [autre: string]: unknown }

export type RelectureBanc = { a_relire: number; relues: number; erreurs: number; borne: number | null; tolerance: number | null; depasse: boolean; restantes: string[] }

export type Essai = {
  essai: number | string
  strategie: string
  scores?: Record<string, number> | null
  vitesse_s?: number | null
  verdict?: string | null
  partiel?: boolean | null
  promu?: boolean | null
  resume?: string | null
  detail?: string | null
  attribution?: { modification?: string; dimension?: string; changement?: string | null; verdict: string; raison?: string | null }[] | null
  [autre: string]: unknown
}

export type Boucle = {
  colonnes: string[]
  minimums: Record<string, number | null>
  essais: Essai[]
  strategies: Record<string, { nom?: string; idee?: string; etat?: string; essais?: number; indice?: number | null; chances?: number | null; raison?: string | null; [autre: string]: unknown }>
  machines: { machines?: { nom: string; carte?: string | null; activite?: string | null; donnees?: number | null; vitesse?: number | null; puissance_w?: number | null; cout_eur?: number | null }[]; total?: { donnees?: number | null; vitesse?: number | null; puissance_w?: number | null; cout_eur?: number | null; minutes_par_mesure?: number | null } | null; mesures?: { essai: number | string; strategie?: string; faites?: number; total?: number; etat?: string }[] } | null
  mis_a_jour: Record<string, { a: string; fige: boolean }>
  controle: { section: string; quoi: string }[]
  sollicitations: { id: string; quoi: string; statut?: string }[]
  bibliotheque?: { etablies_ici: number; a_reverifier: number; pistes: number; sorties: number; harnais: number } | null
  audits?: { porte: string; version?: string | null; passe: boolean; echecs: { id: string; preuve: string }[]; a?: string }[]
  depense?: { lignee: string; illisible?: boolean; identite?: Record<string, unknown> | null; plafond?: Record<string, number> | null; sessions_recherche?: number; sessions_reflexion?: number; mesures?: number; appels?: number; doublons?: string[] }[]
}

export type Attente = { sous_etape: string | null; etape: number; quoi: string; toi?: boolean }

export type Vue = {
  chantier: string
  dossier: string
  ouvert_le: string
  categorie: { id: string; raison?: string | null; citation?: string; a?: string; aucune_ne_convenait?: boolean } | null
  etape_courante: number | null
  attend: Attente | null
  etapes: Etape[]
  registre: Record<string, { valeur: unknown; statut: string; citation: string; libelle?: string | null; sous_etape?: string | null; a?: string; historique?: unknown[] }>
  reprise: { derniere_decision: Decision | null; pendant_absence: { a: string; type: string }[]; derniere_session: string | null; evenements: number }
  regles: string[]
  arbre: { termes: Terme[]; seuils: Record<string, { b1: unknown; b2: unknown }> }
  catalogue: { ecrans: { ecran: string; actions: { action: string; description: string }[] }[]; actions: number } | null
  relecture: { passe: number; relecteurs: string[]; exemples: number; par_critere: Record<string, { accord: number | null; exemples: number; garde: boolean }>; desaccords: number }[]
  besoin: string | null
  mesures: Mesures
  lexique: { a: string; sous_etape: string; notion: string; citation: string }[]
  calcul: Calcul | null
  fabrication: { devis_eur?: number | null; cout_eur: number; depasse: boolean; phases: { nom: string; etat: string; comptes?: Record<string, number>; cout_eur?: number | null; duree_s?: number | null }[]; arret?: string | null; fermee?: string | null } | null
  relecture_banc: RelectureBanc | null
  confirmation_portes?: ConfirmationPortes | null
  usage?: { arrivees: number; scellees: number; etiquetees: number; sonde: number; scellee_min: number; consultations: number; consultations_max: number; generation: number; jugements: { modification: string; verdict: string; pourquoi: string }[] } | null
  boucle: Boucle | null
  livre: boolean
  points: Record<string, { id: string; titre: string }[]>
  neuf?: boolean
  /** Réglages du programme utiles à l'agent : commande du moteur, lanceur d'agents. */
  reglages?: { moteur: string; lanceur_agents: string }
}

/** Une session rattachée à un chantier : elle seule a le volet, la bande, les consignes et les outils. */
export type Rattachement = { chantier: string; role: 'utilisateur' | 'agent'; depuis: string }

export type Fichier = { chemin: string; contenu: string } | null

declare module 'claude-code' {
  interface PluginState {
    'la-boucle-v2': {
      rattachement: Rattachement | null
      vue: Vue | null
      erreur: string | null
      deplie: number[]
      fichier: Fichier
      derniereReponse: number | null
      ssh: string | null
      ouverts: string[]
      suivi: Suivi | null
      nomCourt: boolean
      dernierMessage: number | null
      donneeRelue: { id: string; lot?: string; donnee: unknown; reponse: unknown } | null
    }
  }
}
