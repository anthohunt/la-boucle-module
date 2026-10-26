import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { VUE_ETAPE2, VUE_ETAPES34 } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 130, placement: 'dock', scroll: { offset: 0, bodyRows: 120 }, view: {} } } as const

function monde(on: On, vue: unknown = VUE_ETAPE2) {
  const appels: string[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    appels.push(commande)
    const r = commande === 'ouvrir' || commande === 'etat' ? vue : {}
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => ({ text: e.text }) as never)
  return appels
}

const ouvrir = { command: 'la-boucle-v2', args: 'scelle', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never

describe("Étape 2 — notions comprises et calcul des quantités", () => {
  test('le volet montre le lexique et le calcul du programme (une porte par sortie)', { timeoutMs: 60_000 }, async ($, on) => {
    monde(on)
    await $.command.run(ouvrir)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect((await ui.find({ key: 'basculer-2' }))?.text).toContain("L'étude des données")
      expect(await ui.find({ type: 'Text', text: /Calcul prudent : 7484 données en tout/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /examen : 1226/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /justesse EXECUTER : porte 1 97 % · porte 2 97 % · porte 3 au plus 40 ratés sur 613/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /au niveau visé : 23 sur 100/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /\+10 pts → 100 sur 100/ })).toBeDefined()
      await ui.press({ key: 'lexique' })
      expect(await ui.find({ type: 'Text', text: /Les lots/ })).toBeDefined()
      await ui.press({ key: 'lexique' })
      await ui.unmount()
    }
  })

  test('option portes_filtres : le volet dit « filtres » et montre les chances de livraison et des filtres', { timeoutMs: 60_000 }, async ($, on) => {
    const vue = structuredClone(VUE_ETAPE2) as { calcul: Record<string, unknown> & { portes_par_critere: Record<string, { filtre?: boolean }> } }
    for (const x of Object.values(vue.calcul.portes_par_critere)) x.filtre = true
    Object.assign(vue.calcul, {
      portes_filtres: true,
      chance_livraison_au_vise: 0.9992,
      filtres: { cible_au_vise: 0.9, plafond_a_la_barre: 0.5, chance_au_vise: { selection: 0.9143, pre_evaluation: 0.9127 }, chance_a_la_barre: {}, examen_livraison_seule: null, regle: 'filtre' },
    })
    monde(on, vue)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.find({ key: 'basculer-2' })
    expect(await ui.find({ type: 'Text', text: /justesse EXECUTER : filtres 1 et 2 97 % · porte 3 au plus 40 ratés sur 613/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /livré 100 sur 100, filtre 1 franchi 91 sur 100, filtre 2 91 sur 100/ })).toBeDefined()
    await ui.unmount()
  })

  test("entraînement minimum : le volet dit ce qui fixe l'entraînement", { timeoutMs: 60_000 }, async ($, on) => {
    const vue = structuredClone(VUE_ETAPE2) as { calcul: Record<string, unknown> & { tailles: Record<string, number>; fixe_par: Record<string, string> } }
    vue.calcul.tailles.entrainement = 19249
    vue.calcul.fixe_par.entrainement = 'le cours (lots.entrainement_min : au moins 10\u202f704 hors sélection, parts égales) + la sélection'
    monde(on, vue)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.find({ key: 'basculer-2' })
    expect(await ui.find({ type: 'Text', text: /entraînement \(dont sélection\) : 19249 \(fixé par le cours \(lots\.entrainement_min : au moins 10\u202f704 hors sélection, parts égales\) \+ la sélection\)/ })).toBeDefined()
    await ui.unmount()
  })

  test("borne prévue : un pilote trop petit se dit « à confirmer » sans compromis", { timeoutMs: 60_000 }, async ($, on) => {
    const vue = structuredClone(VUE_ETAPE2) as { calcul: Record<string, unknown> }
    vue.calcul.a_confirmer = ["à confirmer par 299 relectures à l'étape 3 : le pilote n'en a que 10 (1 erreur, borne mesurée 39.4%)"]
    monde(on, vue)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.find({ key: 'basculer-2' })
    expect(await ui.find({ type: 'Text', text: /étiquettes : à confirmer par 299 relectures à l'étape 3/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /compromis à trancher : à confirmer/ })).toBeUndefined()
    await ui.unmount()
  })

  test("borne prévue, étape 3 : l'écart ferme la fabrication ; l'outil confirmer_portes passe au programme", { timeoutMs: 60_000 }, async ($, on) => {
    const v3 = structuredClone(VUE_ETAPES34) as { fabrication: Record<string, unknown>; confirmation_portes?: unknown }
    const motif = "écart à la borne prévue : 1 erreur sur les 41 premières relectures (le plan en permet 0 sur 299 pour une borne de 1.0%) : la fabrication est fermée jusqu'à la réouverture de l'étape 2"
    v3.confirmation_portes = { etat: 'ecart', motif, borne_prevue: 0.01, relectures_plan: 299, erreurs_permises: 0, relues: 41, erreurs: 1 }
    v3.fabrication.fermee = motif
    const appels = monde(on, v3)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'basculer-3' })
    expect(await ui.find({ type: 'Text', text: /fabrication fermée : écart à la borne prévue/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\s*écart à la borne prévue : 1 erreur sur les 41 premières relectures/ })).toBeDefined()
    await ui.unmount()
    await $.tool.call({ tool: 'mcp__la-boucle-v2__confirmer_portes' } as never)
    expect(appels).toContain('confirmer_portes')
  })

  test("l'outil calcul passe au programme", { timeoutMs: 60_000 }, async ($, on) => {
    const appels = monde(on)
    await $.command.run(ouvrir)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__calcul' } as never)
    expect(appels).toContain('calcul')
  })
})
