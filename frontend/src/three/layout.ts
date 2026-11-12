/**
 * Posição 3D de cada dispositivo. Fica só no frontend, indexada pelo mesmo id do
 * cadastro: o backend não sabe nada sobre a cena.
 */
export interface Spot {
  x: number
  y: number
  z: number
}

export const ROOM = { width: 16, depth: 11, height: 4.2 } as const

export const RACKS = [
  { id: 'rack01', x: -2.2, z: 0.4 },
  { id: 'rack02', x: 1.6, z: 0.4 },
] as const

export const RACK_SIZE = { width: 1.5, height: 2.4, depth: 1.1 } as const

export const POSITIONS: Record<string, Spot> = {
  'temp-rack01': { x: -2.2, y: 1.7, z: 1.0 },
  'temp-rack02': { x: 1.6, y: 1.7, z: 1.0 },
  'pwr-rack01': { x: -2.2, y: 0.7, z: 1.0 },
  'hum-sala': { x: -7.85, y: 2.0, z: 1.5 },
  'lux-sala': { x: 3.3, y: 3.0, z: -5.3 },
  'door-sala': { x: 7.85, y: 2.4, z: 2.6 },
  'crac-01': { x: -5.6, y: 1.25, z: -3.9 },
  'crac-02': { x: 5.6, y: 1.25, z: -3.9 },
  'fan-exaustor': { x: 7.9, y: 3.0, z: -1.6 },
  'light-sala': { x: 0, y: 4.05, z: 0.4 },
  'siren-sala': { x: -7.85, y: 3.2, z: -2.2 },
}

/** Dispositivo novo do cadastro ganha um lugar na prateleira da parede do fundo. */
export function shelfSpot(index: number): Spot {
  return { x: -2.6 + (index % 6) * 0.9, y: 2.9 - Math.floor(index / 6) * 0.5, z: -5.3 }
}
