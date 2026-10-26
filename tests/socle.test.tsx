import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { VUE_APRES_BIENVENUE, VUE_NEUF, VUE_REPRISE } from './fixtures'
import { PRESENTATION } from '../hooks/textes'

const BASE = { sections: [{ id: 'intro', text: 'base', scope: 'shared' as const }] }
const COMPOSE = { model: 'claude-opus-5-5', promptModel: 'claude-opus-5-5', surfaces: [], tools: [], outputStyle: null, traits: [] }
const OUTIL = 'mcp__la-boucle-v2__'
const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 90, placement: 'dock', scroll: { offset: 0, bodyRows: 60 }, view: {} } } as const

type Appel = { commande: string; args: Record<string, unknown> }

/** Le monde sous le mod : le programme répond par commande (vues fabriquées par le vrai programme). */
function monde(on: On, reponses: Record<string, unknown>, declares: string[] = []) {
  const appels: Appel[] = []
  const outils: string[] = []
  const soumis: string[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    const args = JSON.parse(String(e.init?.stdin ?? '{}')) as Record<string, unknown>
    appels.push({ commande, args })
    const r = reponses[commande] ?? {}
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }) + '\n', stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => (outils.push((e as { name: string }).name), { value: { tool: `${OUTIL}${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('ui.close', async () => ({ value: undefined }) as never)
  on('command.register', async (_$, e) => (declares.push((e as { name: string }).name), { value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('session.start', async (_$, e) => ({ cwd: (e as { cwd: string }).cwd }) as never)
  on('prompt.compose', () => BASE)
  on('prompt.submit', async (_$, e) => (soumis.push(e.text), { text: e.text }) as never)
  return { appels, outils, soumis }
}

const ouvrir = (args: string) => ({ command: 'la-boucle-v2', args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } }) as never
const sections = async ($: { prompt: { compose: (i: never) => Promise<{ sections: readonly { id: string; text: string }[] }> } }) => (await $.prompt.compose(COMPOSE as never)).sections

describe('seule la session rattachée est une session de la boucle', () => {
  test('session non rattachée : même prompt système, aucun outil, outil refusé', { timeoutMs: 60_000 }, async ($, on) => {
    const { appels, outils } = monde(on, {})
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as never)
    expect((await sections($ as never)).map(s => s.id)).toEqual(['intro'])
    expect(outils).toEqual([])
    expect(appels.filter(a => a.commande !== 'etat' && a.commande !== 'suivi')).toEqual([])
    const r = await $.tool.call({ tool: `${OUTIL}decision`, sous_etape: 'E1.2', resume: 'x', citation: 'y' } as never)
    expect(JSON.stringify(r)).toContain("n'est pas rattachée")
  })

  test('/la-boucle <chantier> rattache : outils, consignes ; /la-boucle off détache', { timeoutMs: 60_000 }, async ($, on) => {
    const { appels, outils } = monde(on, { ouvrir: VUE_NEUF, etat: VUE_NEUF, evenement: {} })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as never)
    const r = await $.command.run(ouvrir('Essai'))
    expect(r.text).toContain('Bienvenue dans La boucle')
    expect(appels[0]).toEqual({ commande: 'ouvrir', args: expect.objectContaining({ chantier: 'essai', role: 'utilisateur' }) })
    expect(outils).toEqual(expect.arrayContaining(['etat', 'decision', 'avancer', 'categorie', 'ecrire', 'lire', 'rouvrir', 'registre']))
    const s = await sections($ as never)
    expect(s.map(x => x.id)).toEqual(['intro', 'la-boucle-v2:protocole'])
    expect(s[1]?.text).toContain('Sous-étape E1.1')
    expect(s[1]?.text).toContain('« autre chose, précise-moi »')
    expect(s[1]?.text).toContain("Comment tu écris à l'utilisateur")
    expect(s[1]?.text).toContain('Agent de recherche, à toutes les étapes')

    const off = await $.command.run(ouvrir('off'))
    expect(off.text).toContain('session normale')
    expect((await sections($ as never)).map(x => x.id)).toEqual(['intro'])
  })
})

describe('/la-boucle : le nom court reste libre tant que l’option est éteinte', () => {
  test('par défaut : seul /la-boucle-v2 est déclaré, /la-boucle reste à un autre module', { timeoutMs: 60_000 }, async ($, on) => {
    const declares: string[] = []
    const { appels } = monde(on, { ouvrir: VUE_NEUF, etat: VUE_NEUF }, declares)
    on('command.run', async () => ({ text: 'autre module' }) as never)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as never)
    expect(declares).toEqual(['la-boucle-v2'])
    expect((await $.command.run({ ...(ouvrir('essai') as object), command: 'la-boucle' } as never)).text).toBe('autre module')
    expect(appels.filter(a => a.commande === 'ouvrir')).toEqual([])
    expect((await $.command.run(ouvrir('essai'))).text).toContain('Bienvenue')
  })

  test('option nom_court (nom court pris) : /la-boucle ouvre le chantier', { timeoutMs: 60_000, options: { nom_court: true } }, async ($, on) => {
    const declares: string[] = []
    monde(on, { ouvrir: VUE_NEUF, etat: VUE_NEUF }, declares)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as never)
    expect(declares).toEqual(['la-boucle-v2', 'la-boucle'])
    expect((await $.command.run({ ...(ouvrir('essai') as object), command: 'la-boucle' } as never)).text).toContain('Bienvenue')
  })
})

describe('E1.1 — la bienvenue, puis les décisions passent par le programme', () => {
  test("le premier message de l'utilisateur valide la bienvenue, mot pour mot", { timeoutMs: 60_000 }, async ($, on) => {
    const { appels } = monde(on, { ouvrir: VUE_NEUF, etat: VUE_APRES_BIENVENUE, evenement: {}, avancer: {} })
    await $.command.run(ouvrir('essai'))
    await $.prompt.submit({ text: "j'ai compris, je suis prêt", origin: { kind: 'composer' } } as never)
    const av = appels.find(a => a.commande === 'avancer')
    expect(av?.args).toEqual(expect.objectContaining({ chantier: 'essai', sous_etape: 'E1.1', etat: 'validee', citation: "j'ai compris, je suis prêt" }))
    const s = await sections($ as never)
    expect(s[1]?.text).toContain('Sous-étape E1.2')
  })

  test("un outil de l'agent passe au programme avec le chantier de la session", { timeoutMs: 60_000 }, async ($, on) => {
    const { appels } = monde(on, { ouvrir: VUE_APRES_BIENVENUE, etat: VUE_APRES_BIENVENUE, decision: { decision: { citation: "oui, c'est ça" } } })
    await $.command.run(ouvrir('essai'))
    const r = await $.tool.call({ tool: `${OUTIL}decision`, sous_etape: 'E1.2', resume: 'Vue globale acceptée', citation: "oui, c'est ça", option: 'A' } as never)
    expect(JSON.stringify(r)).toContain("oui, c'est ça")
    const d = appels.find(a => a.commande === 'decision')
    expect(d?.args).toEqual({ chantier: 'essai', sous_etape: 'E1.2', resume: 'Vue globale acceptée', citation: "oui, c'est ça", option: 'A' })
  })
})

describe('reprendre un chantier', () => {
  test("la reprise donne à l'agent la dernière décision et ce qui attend", { timeoutMs: 60_000 }, async ($, on) => {
    monde(on, { ouvrir: VUE_REPRISE, etat: VUE_REPRISE })
    const r = await $.command.run(ouvrir('essai'))
    expect(r.text).toContain('repris')
    const ctx = JSON.stringify((r as { context?: string[] }).context ?? [])
    expect(ctx).toContain("oui, c'est ça")
    expect(ctx).toContain('3 à 5 lignes')
  })
})

describe('le volet de contrôle', () => {
  test("arbre des 5 étapes, ce qui t'attend en tête, étape courante dépliée, fichier sauvegardé, rouvrir d'un clic", { timeoutMs: 60_000 }, async ($, on) => {
    const { soumis } = monde(on, { ouvrir: VUE_REPRISE, etat: VUE_REPRISE })
    await $.command.run(ouvrir('essai'))
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ type: 'Text', text: 'À toi' })).toBeDefined()
      expect(await ui.find({ key: 'aller' })).toBeDefined()
      const titres = ["L'objectif", "L'étude des données", 'Le banc', 'La boucle', 'Le livrable']
      for (const [i, titre] of titres.entries()) expect((await ui.find({ key: `basculer-${i + 1}` }))?.text).toContain(titre)
      expect(await ui.find({ type: 'Text', text: /^▾ 1\. L'objectif$/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Le besoin/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Le type de donnée/ })).toBeUndefined()
      // Volet épuré : le résumé de la décision au clic sur la ligne, jamais le message brut ;
      // le besoin rédigé replié ; « rouvrir » seulement dans le détail.
      expect(await ui.find({ type: 'Text', text: /Vue globale acceptée/ })).toBeUndefined()
      await ui.press({ key: 'ligne-E1.2' })
      expect(await ui.find({ type: 'Text', text: /Vue globale acceptée/ })).toBeDefined()
      await ui.press({ key: 'ligne-E1.2' })
      expect(await ui.find({ type: 'Text', text: /oui, c'est ça/ })).toBeUndefined()
      expect(await ui.find({ key: 'basculer-besoin' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /chantier\.json|besoin\.md/ })).toBeUndefined()
      expect(await ui.find({ key: 'rouvrir-se-E1.1' })).toBeUndefined()
      await ui.press({ key: 'ligne-E1.1' })
      expect(await ui.find({ key: 'rouvrir-se-E1.1' })).toBeDefined()
      await ui.press({ key: 'basculer-2' })
      expect(await ui.find({ type: 'Text', text: /Le type de donnée/ })).toBeDefined()
      await ui.press({ key: 'basculer-2' })
      await ui.press({ key: 'basculer-1' })
      expect(await ui.find({ type: 'Text', text: /^▸ 1\. L'objectif$/ })).toBeDefined()
      expect(await ui.find({ key: 'rouvrir-se-E1.1' })).toBeUndefined()
      await ui.press({ key: 'basculer-1' })
      expect(await ui.find({ key: 'rouvrir-se-E1.1' })).toBeDefined()
      await ui.press({ key: 'ligne-E1.1' })
      await ui.unmount()
    }
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'ligne-E1.1' })
    await ui.press({ key: 'rouvrir-se-E1.1' })
    expect(soumis.at(-1)).toBe('Je veux rouvrir la sous-étape E1.1 — La bienvenue.')
    await ui.unmount()
  })

  test('la bande au-dessus de l’invite rappelle le chantier, l’étape et ce qui attend', { timeoutMs: 60_000 }, async ($, on) => {
    monde(on, { ouvrir: VUE_REPRISE, etat: VUE_REPRISE })
    await $.command.run(ouvrir('essai'))
    const ui = await $.ui.mount({ plugin: 'la-boucle-v2', component: 'AbovePrompt', requestId: 'band', props: { bodyColumns: 120 }, surface: 'terminal' } as never)
    expect(await ui.find({ type: 'Text', text: /essai · étape 1 L'objectif · t'attend/ })).toBeDefined()
    await ui.unmount()
  })
})

describe('Transport — le programme joint en local ou, si un hôte est réglé, par SSH', () => {
  const essai = async ($: never, on: On, presents: string[]) => {
    const argvs: string[][] = []
    mock.store(on)
    mock.clock(on, { now: Date.parse('2026-10-15T08:00:00Z') })
    mock.env(on, {})
    on('fs.stat', async (_$, e) => (presents.some(p => String((e as { path: string }).path).endsWith(p)) ? { value: { kind: 'file', size: 1, mtimeMs: 0 } } : { deny: 'ENOENT' }) as never)
    on('process.run', async (_$, e) => (argvs.push([...e.argv]), { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: { chantiers: [] } }) + '\n', stderr: '' } }) as never)
    on('command.register', async () => ({ value: undefined }) as never)
    on('session.id', async () => ({ value: 'session-test' }) as never)
    on('session.start', async (_$, e) => ({ cwd: (e as { cwd: string }).cwd }) as never)
    const s = $ as unknown as { session: { start: (e: never) => Promise<unknown> }; command: { run: (e: never) => Promise<{ text: string }> } }
    await s.session.start({ surface: 'desktop', isInteractive: true, cwd: 'C:\\Users\\operateur' } as never)
    const r = await s.command.run(ouvrir(''))
    return { argvs, r }
  }

  test('Windows avec Git et un hôte réglé : le SSH de Git (celui de Windows reste bloqué quand Claude Code le lance)', { timeoutMs: 60_000, options: { hote: 'operateur@serveur.example', programme_distant: '/opt/la-boucle/programme/boucle.py' } }, async ($, on) => {
    const { argvs, r } = await essai($ as never, on, ['C:\\Program Files\\Git\\usr\\bin\\ssh.exe'])
    expect(argvs[0]![0]).toBe('C:\\Program Files\\Git\\usr\\bin\\ssh.exe')
    expect(argvs[0]!).toContain('operateur@serveur.example')
    expect(argvs[0]!.at(-1)).toContain('/opt/la-boucle/programme/boucle.py')
    expect(r.text).toContain('/la-boucle-v2 <chantier>')
  })

  test('hôte réglé, pas de Git : ssh du système', { timeoutMs: 60_000, options: { hote: 'operateur@serveur.example' } }, async ($, on) => {
    const { argvs } = await essai($ as never, on, [])
    expect(argvs[0]![0]).toBe('ssh')
  })

  test('sans hôte (défaut) : le programme du module tourne en local, sans SSH', { timeoutMs: 60_000 }, async ($, on) => {
    const { argvs } = await essai($ as never, on, [])
    expect(argvs[0]![0]).toBe('python3')
    expect(argvs[0]!).toContain('-B')
    expect(argvs[0]!.some(x => x.endsWith('programme/boucle.py'))).toBe(true)
  })
})

describe('E2.10 — un choix chiffré se montre par un tableau de chiffres', () => {
  test('la règle de présentation le demande, avant toute image', { timeoutMs: 60_000 }, async () => {
    expect(PRESENTATION).toContain('Un choix chiffré')
    expect(PRESENTATION).toContain('refuser un bon modèle par malchance')
  })
})

describe('E2.2.1 — la stratégie de génération : la diversité se mesure par le programme', () => {
  test("l'outil diversite passe au programme avec le chantier, le lot et les graines", { timeoutMs: 60_000 }, async ($, on) => {
    const { appels } = monde(on, { ouvrir: VUE_APRES_BIENVENUE, etat: VUE_APRES_BIENVENUE, diversite: { passe: false, motifs: ['trop de quasi-doublons'] } })
    await $.command.run(ouvrir('essai'))
    const r = await $.tool.call({ tool: `${OUTIL}diversite`, fichier: 'etape2/pilote/donnees.jsonl', champ: 'phrase', graines: 'etape2/graines.jsonl' } as never)
    expect(JSON.stringify(r)).toContain('quasi-doublons')
    const d = appels.find(a => a.commande === 'diversite')
    expect(d?.args).toEqual({ chantier: 'essai', fichier: 'etape2/pilote/donnees.jsonl', champ: 'phrase', graines: 'etape2/graines.jsonl' })
  })
})
