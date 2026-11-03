/**
 * Cenas: ordinais (escuro -> extrema). Cor = rampa sequencial de um único
 * matiz (azul), passo mais claro = mais luz, escolhida para o fundo escuro.
 * A cor nunca é o único canal: todo uso traz o rótulo da cena junto.
 */
export const SCENE_ORDER = ['escuro', 'ambiente', 'alta', 'extrema'] as const

export const SCENE_LABEL: Record<string, string> = {
  escuro: 'Escuro',
  ambiente: 'Ambiente',
  alta: 'Alta',
  extrema: 'Extrema',
  apagada: 'Apagada',
}

export const SCENE_COLOR: Record<string, string> = {
  escuro: '#184f95',
  ambiente: '#2a78d6',
  alta: '#6da7ec',
  extrema: '#b7d3f6',
}

export const UNKNOWN_SCENE_COLOR = '#55544f'

export const sceneLabel = (k: string | null | undefined) => (k ? SCENE_LABEL[k] ?? k : '—')
export const sceneColor = (k: string | null | undefined) => (k && SCENE_COLOR[k]) || UNKNOWN_SCENE_COLOR
export const sceneIndex = (k: string) => SCENE_ORDER.indexOf(k as (typeof SCENE_ORDER)[number])

export const SCENE_RANGE: Record<string, string> = {
  escuro: '< 150',
  ambiente: '150 – 399',
  alta: '400 – 999',
  extrema: '≥ 1000',
}
