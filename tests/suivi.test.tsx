import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { SUIVI, VUE_ETAPE1 } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 120, placement: 'dock', scroll: { offset: 0, bodyRows: 120 }, view: {} } } as const

function monde(on: On) {
  const appels: { commande: string; args: Record<string, unknown> }[] = []
  mock.store(on)
  const horloge = mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    appels.push({ commande, args: JSON.parse(String(e.init?.stdin ?? '{}')) })
    const r = commande === 'ouvrir' || commande === 'etat' ? VUE_ETAPE1 : commande === 'suivi' ? SUIVI : { arret: 'session arrêtée' }
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('ui.toast', async () => ({ value: undefined }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => ({ text: e.text }) as never)
  return { appels, horloge }
}

const ouvrir = { command: 'la-boucle-v2', args: 'essai', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never

describe('agents, comptes, budget dans le volet', () => {
  test("fiches d'agents (rôle, sous-étape, depuis, compte, lien), travail bloqué en rouge, arrêt depuis le volet", { timeoutMs: 60_000 }, async ($, on) => {
    const { appels, horloge } = monde(on)
    await $.command.run(ouvrir)
    await horloge.settle()
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ type: 'Text', text: /^Moteur · comptes Claude des agents/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /rédacteur des définitions/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /E1\.6 · définitions au propre · depuis .* · compte compte-b/ })).toBeDefined()
      expect(await ui.find({ type: 'Link', text: 'Ouvrir sa conversation' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Bloqué ou en panne/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /parti sur compte-b : compte-c proche de sa limite/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Compte B : 5 h 10 % · semaine 31 %/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Compte C : 5 h 95 % · semaine 20 % · proche de sa limite/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Budget : prévu 0\.44 € · validé 0\.50 € · dépensé 0\.30 €/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /arbitrage \(fournisseur-b grand-modele\).*attend ton accord/ })).toBeDefined()
      await ui.unmount()
    }
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'arreter-relecteur-a' })
    expect(appels.find(a => a.commande === 'arreter_agent')?.args).toEqual({ chantier: 'essai', nom: 'relecteur-a' })
    await ui.press({ key: 'brancher-compte-a' })
    expect(appels.find(a => a.commande === 'comptes')?.args).toEqual({ chantier: 'essai', action: 'brancher', compte: 'compte-a' })
    await ui.press({ key: 'debrancher-compte-c' })
    expect(appels.filter(a => a.commande === 'comptes').at(-1)?.args).toEqual({ chantier: 'essai', action: 'debrancher', compte: 'compte-c' })
    await ui.unmount()
  })

  test('les outils comptes, agent, depense passent au programme', { timeoutMs: 60_000 }, async ($, on) => {
    const { appels } = monde(on)
    await $.command.run(ouvrir)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__comptes', action: 'brancher', compte: 'compte-a' } as never)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__agent', nom: 'pilote', role: 'pilote', sous_etape: 'E2.3' } as never)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__depense', action: 'accepter', passe: 'pilote-gen', citation: 'oui', montant_accepte_eur: 1 } as never)
    expect(appels.map(a => a.commande).filter(c => ['comptes', 'agent', 'depense'].includes(c))).toEqual(['comptes', 'agent', 'depense'])
  })


  test("un travail fini revient dans le chat ; bloqué, il est relancé ; absent, un message de notification court", { timeoutMs: 60_000 }, async ($, on) => {
    const soumis: string[] = []
    const appels: { argv: readonly string[]; commande: string }[] = []
    let tour = 0
    const agentsAvant = [{ nom: 'redacteur', role: 'rédacteur des définitions', sous_etape: 'E1.6', etat: 'travaille', depuis: '2026-10-14T17:00:00Z' },
      { nom: 'pilote', role: 'pilote', sous_etape: 'E2.3', etat: 'travaille', depuis: '2026-10-14T17:00:00Z', relance: ['true'] }]
    const agentsApres = [{ ...agentsAvant[0], etat: 'fini' }, { ...agentsAvant[1], etat: 'panne', bloque: true, relancable: true }]
    mock.store(on)
    const horloge = mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
    mock.env(on, {})
    on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
    on('process.run', async (_$, e) => {
      const commande = String(e.argv[e.argv.length - 1])
      appels.push({ argv: e.argv, commande })
      const suiviCourant = { ...SUIVI, agents: commande === 'suivi' && tour++ === 0 ? agentsAvant : agentsApres }
      const r = commande === 'ouvrir' || commande === 'etat' ? VUE_ETAPE1 : commande === 'suivi' ? suiviCourant : {}
      return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
    })
    on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
    on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
    on('ui.toast', async () => ({ value: undefined }) as never)
    on('command.register', async () => ({ value: undefined }) as never)
    on('session.id', async () => ({ value: 'session-test' }) as never)
    on('session.start', async (_$, e) => ({ cwd: (e as { cwd: string }).cwd }) as never)
    on('prompt.submit', async (_$, e) => (soumis.push(e.text), { text: e.text }) as never)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as never)
    await $.command.run(ouvrir)
    await horloge.settle()
    await horloge.advance(60_000)
    await horloge.settle()
    await horloge.advance(60_000)
    await horloge.settle()
    expect(soumis.some(t => t.startsWith('[la-boucle] rédacteur des définitions a fini (E1.6)'))).toBe(true)
    expect(appels.some(a => a.commande === 'relancer')).toBe(true)
    const notifs = appels.filter(a => a.commande === 'signaler')
    expect(notifs.length).toBe(2)
  })
})
