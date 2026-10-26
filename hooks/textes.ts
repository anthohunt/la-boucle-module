// Les textes du mode : bienvenue (E1.1), consignes de l'agent, reprise. Génériques : tout ce qui est
// propre à un chantier vient de son état (la vue rendue par le programme).

import type { SousEtape, Vue } from '../types'

export const QUI: Record<SousEtape['qui'], string> = { moi: 'toi', agent: 'un agent', programme: 'le programme' }

export const ETAT: Record<string, string> = {
  a_faire: 'à faire',
  en_cours: 'en cours',
  a_valider: 'à valider par toi',
  validee: 'validée',
  scellee: 'scellée',
  ouverte: 'ouverte',
  fermee: 'pas encore ouverte',
  a_sceller: 'à sceller',
}

/** Le bandeau de bienvenue d'un chantier neuf (E1.1) : 3 écrans au plus, sans question. */
export function bienvenue(v: Vue): string {
  return [
    `**Bienvenue dans La boucle — chantier « ${v.chantier} ».**`,
    '',
    "La boucle sert à rendre un processus autonome avec un petit modèle : un modèle qui tient sur ta machine, entraîné pour décider exactement ce que tu attends, et prouvé sur un examen avant d'être livré.",
    '',
    'Le chantier suit 5 étapes :',
    ...v.etapes.map(e => `${e.n}. **${e.titre}** — ${e.resume}`),
    '',
    "Comment ça marche : tu discutes avec l'agent ici, dans le chat ; le volet de contrôle, à droite, suit tout (où tu en es, ce qui t'attend, chaque décision avec tes mots, où chaque résultat est enregistré).",
    '',
    'Ce que tu décides toi :',
    ...v.etapes.map(e => `• étape ${e.n} : ${e.tu_decides}`),
    '',
    'Réponds quand tu es prêt (par exemple « j’ai compris, je suis prêt ») : ta réponse valide la bienvenue et ouvre la description de ton besoin.',
  ].join('\n')
}

function enCours(v: Vue): SousEtape[] {
  const e = v.etapes.find(x => x.n === v.etape_courante)
  return (e?.sous_etapes ?? []).filter(s => s.etat === 'en_cours' || s.etat === 'a_valider')
}

/** Comment l'agent écrit à l'utilisateur, à chaque message. */
export const PRESENTATION = [
  "Comment tu écris à l'utilisateur, à chaque message (aussi important que le fond) :",
  "1. Un message = une idée et une question. Ne redis pas ce qu'il vient de valider : une demi-ligne suffit (« Cadrage validé. »).",
  '2. Une ligne de titre en gras qui dit où on en est, en 2 à 5 mots (ex. « **Couche 2 · exécuter** »).',
  '3. Court : 6 lignes au plus avant la question. Phrases de moins de 20 mots, une idée par phrase, une ligne vide entre les blocs.',
  "4. Ce qui se compare (termes, options, exemples) va dans un tableau à 2 ou 3 colonnes, jamais dans un paragraphe. Un exemple tient en une ligne et seulement s'il éclaire. Un choix chiffré (quantité, risque, statistique) se présente D'ABORD par le tableau des chiffres du programme : une colonne par option, une ligne par conséquence concrète (ex. livrer un modèle sous la barre, refuser un bon modèle par malchance) ; l'image vient après, en deux lignes.",
  '5. La question en une phrase, puis les choix en liste A/B/C, chaque option en 3 à 8 mots ; la dernière est toujours « autre chose, précise-moi ».',
  "6. Gras sur 2 ou 3 termes clés au plus. Aucun jargon interne : pas d'identifiant (p01, E1.5), de nom de fichier ni de nom d'outil ; ses mots à lui.",
  "7. Relis avant d'envoyer : un bloc de plus de 3 lignes sans retour à la ligne = à couper.",
  '',
].join('\n')

/** L'agent de recherche, proposé à toutes les étapes. */
export const recherche = (v: Vue) => [
  "Agent de recherche, à toutes les étapes :",
  "• Dès qu'une question touche une notion où un savoir extérieur aide (définir ou découper un terme, choisir une méthode, un seuil, un chiffre de référence) ou que l'utilisateur hésite, ajoute aux choix une option « lancer un agent de recherche sur <sujet précis> ».",
  `• S'il accepte : un agent par sujet précis (plusieurs sujets = plusieurs agents en parallèle), lancé par ${v.reglages?.lanceur_agents ? v.reglages.lanceur_agents + ' <nom> <consigne>' : 'le lanceur d’agents de l’opérateur (réglage agents.lanceur)'} (modèle le plus capable, effort élevé par défaut), déclaré avec l'outil agent (rôle « recherche », sous-étape, quoi).`,
  "• Sa consigne : chercher en ligne d'abord, puis rendre 2 ou 3 propositions illustrées sur le cas du chantier, avec leurs sources, en TL;DR dans <nom>.rendu.md.",
  "• Dis en une ligne ce qui est lancé, continue sur un autre point si possible, puis présente ses propositions en A/B/C dès qu'il a fini.",
  '',
].join('\n')

/** Les consignes de l'agent, ajoutées au prompt système des seules sessions rattachées. */
export function protocole(v: Vue, role: 'utilisateur' | 'agent'): string {
  const lignes: string[] = [
    `MODE LA BOUCLE (v2) — chantier « ${v.chantier} »${role === 'agent' ? ' — tu es un agent lancé par la boucle pour ce chantier' : ''}.`,
    "Tu conduis le chantier avec l'utilisateur, dans le chat. Le volet de contrôle (à droite) lit l'état du chantier dans ses fichiers : il n'est juste que si chaque geste passe par tes outils mcp__la-boucle-v2__*.",
    '',
    'Règles, sans exception :',
    ...v.regles.map((r, i) => `${i + 1}. ${r}`),
    '',
    PRESENTATION,
    ...(role === 'utilisateur' ? [recherche(v)] : []),
    ...(v.reglages?.moteur ? [`Moteur d’entraînement (étapes 3 et 4) : \`${v.reglages.moteur}\` (dépôt la-boucle-engine), sous-commandes sceller, verifier, noter, run, tableau.`, ''] : []),
  ]
  const actives = enCours(v)
  if (v.attend && !v.attend.sous_etape) lignes.push(`Ce qui attend : ${v.attend.quoi}.`)
  for (const s of actives) {
    lignes.push(`Sous-étape ${s.id} — ${s.titre} (qui agit : ${QUI[s.qui]} ; état : ${ETAT[s.etat]}).`)
    if (s.entree) lignes.push(`Entrée : ${s.entree}`)
    if (s.sorties.length) lignes.push(`Sortie à écrire : ${s.sorties.map(o => o.chemin).join(', ')}`)
    if (s.consigne) lignes.push(`Consigne : ${s.consigne}`)
    const pts = v.points[s.id]
    if (pts) {
      const tranches = new Set(s.decisions.filter(d => d.point && d.statut !== 'rouvert').map(d => d.point))
      const ouverts = pts.filter(p => !tranches.has(p.id))
      lignes.push(`Points (${pts.length - ouverts.length}/${pts.length} tranchés) ; prochains : ${ouverts.slice(0, 3).map(p => `${p.id} ${p.titre}`).join(' ; ') || 'aucun, tous tranchés'}.`)
    }
    if (s.decisions.length) lignes.push(`Déjà décidé ici : ${s.decisions.slice(-5).map(d => `« ${d.citation} » (${d.resume})`).join(' ; ')}`)
    lignes.push('')
  }
  if (!actives.length && v.attend) lignes.push(`Ce qui attend l'utilisateur : ${v.attend.quoi}.`)
  if (v.categorie) lignes.push(`Catégorie du besoin : ${v.categorie.id}.`)
  lignes.push(`Dossier du chantier : ${v.dossier}. Écris les sorties avec l'outil ecrire, jamais à la main.`)
  return lignes.join('\n')
}

/** Ce que l'agent reçoit à la reprise d'un chantier, pour résumer en 3 à 5 lignes. */
export function contexteReprise(v: Vue): string {
  const d = v.reprise.derniere_decision
  const pendant = v.reprise.pendant_absence
  return [
    `Le chantier « ${v.chantier} » est repris dans cette session. Résume à l'utilisateur, en 3 à 5 lignes : la dernière décision, le travail fini ou en panne pendant son absence, la prochaine chose à faire ; puis reprends la discussion sur la sous-étape en cours, sans lui faire rien réexpliquer.`,
    `Dernière décision : ${d ? `« ${d.citation} » — ${d.resume} (${d.a})` : 'aucune'}.`,
    `Pendant l'absence : ${pendant.length ? pendant.map(ev => `${ev.type} (${ev.a})`).join(', ') : 'rien de noté'}.`,
    `Ce qui attend : ${v.attend?.quoi ?? 'rien'}.`,
  ].join('\n')
}

/** La date d'un horodatage du programme, à l'heure de Paris. */
export function heure(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' })
}

/** Le texte tapé par l'utilisateur, sans les blocs <system-reminder> que l'appli ajoute au message. */
export function sansRappels(texte: string): string {
  return texte.replace(/<system-reminder>[\s\S]*?(<\/system-reminder>|$)/g, '').trim()
}

/** E1.1 : le message qui dit « je suis prêt » (et lui seul) valide la bienvenue. Une question ou une remarque
 * la laisse ouverte. Règle fixe, sans modèle. */
export function ditPret(texte: string): boolean {
  const t = sansRappels(texte).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[’']/g, "'")
  if (/\bpas\s+(encore\s+|tout\s+a\s+fait\s+)?(pret|compris)/.test(t)) return false
  return /\b(pret|prete|compris|c'est parti|allons[- ]y|on y va|go|ok|okay|d'accord|vas[- ]y|on commence|commencons|on demarre)\b/.test(t)
}
