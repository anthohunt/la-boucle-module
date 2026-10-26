// Le pont vers le programme du module (programme/boucle.py) : en local, ou par SSH vers l'hôte réglé.
// Les paramètres passent en JSON sur l'entrée standard (aucun échappement de shell), la réponse revient en JSON.
// Fonctions pures : l'appel lui-même (qui tient $) est dans register.tsx.

/** Emplacement du programme dans le dossier du module (`$.plugin.root`), et son nom dans le dossier du module. */
export const PROGRAMME_RELATIF = 'programme/boucle.py'

export type Reponse<T> = { ok: true; resultat: T } | { ok: false; refus: string }

/** Le client SSH sous Windows : celui de Git. L'OpenSSH de Windows, lancé par Claude Code, reste bloqué à la fermeture
 *  de sa sortie et l'appel finit en dépassement de délai ; celui de Git répond. */
export const SSH_WINDOWS = 'C:\\Program Files\\Git\\usr\\bin\\ssh.exe'

/** La ligne de commande : python en local (le programme du module), sinon SSH vers l'hôte réglé (`hote`), où le
 *  programme est installé à `programmeDistant`. L'hôte vide veut dire « ici ». */
export function argvPour(hote: string, programme: string, commande: string, ssh = 'ssh', python = 'python3', programmeDistant = ''): string[] {
  if (!hote) return [python, '-B', programme, commande]
  return [
    ssh, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', hote,
    `${python} -B ${programmeDistant || programme} ${commande}`,
  ]
}

/** La réponse du programme : sa dernière ligne JSON, ou un refus lisible. */
export function lireReponse<T>(stdout: string, stderr: string, code: number): Reponse<T> {
  const ligne = stdout.trim().split('\n').pop() ?? ''
  if (!ligne) return { ok: false, refus: `Programme muet (code ${code}) : ${stderr.trim().slice(0, 300)}` }
  try {
    return JSON.parse(ligne) as Reponse<T>
  } catch {
    return { ok: false, refus: `Réponse illisible du programme : ${ligne.slice(0, 300)}` }
  }
}

/** Ce qui a changé entre deux relevés d'agents : les travaux finis et ceux qui viennent de bloquer. */
export function transitions<A extends { nom: string; etat: string; bloque?: boolean }>(avant: A[] | undefined, apres: A[]): { finis: A[]; bloques: A[] } {
  const prec = new Map((avant ?? []).map(a => [a.nom, a]))
  const finis = apres.filter(a => a.etat === 'fini' && prec.has(a.nom) && prec.get(a.nom)!.etat !== 'fini')
  const bloques = apres.filter(a => a.bloque && !(prec.get(a.nom)?.bloque))
  return { finis, bloques }
}
