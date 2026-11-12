import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import type { Device, Status } from '@/types/api'
import { POSITIONS, RACK_SIZE, RACKS, ROOM, shelfSpot, type Spot } from './layout'

/** Tudo o que a cena sabe do mundo: nada aqui fala com o simulador. */
export interface TwinData {
  devices(): Device[]
  status(id: string): Status
  /** Última leitura, apenas se ainda estiver fresca. */
  metrics(id: string): Record<string, number> | undefined
  temperature(): number | undefined
}

export interface Twin {
  dispose(): void
  select(id: string | null): void
}

const STATUS_COLOR: Record<Status, number> = {
  ok: 0x2ed0ba,
  warning: 0xf6b53f,
  critical: 0xff4a36,
  offline: 0x6b7280,
}

const BACKDROP = 0x050505
const ACCENT = 0x5aa8ff
const HOME_POSITION = new THREE.Vector3(7, 10.5, 18)
const HOME_TARGET = new THREE.Vector3(0, 1.2, -0.6)

/** Racks sem sensor próprio, que completam a fileira da sala. */
const FILLER_RACKS_X = [-4.1, -0.3, 3.5]

const SERVER_UNITS = 9
const LEDS_PER_UNIT = 3
const AIR_PER_DUCT = 44
const HEAT_PARTICLES = 80

/** Luminosidade somada pela lâmpada; o resto é luz natural (physics.py). */
const LAMP_LUX = 430
const DAYLIGHT_LUX = 320

interface Item {
  id: string
  marker: THREE.Mesh
  ring: THREE.Mesh
  label: CSS2DObject
  element: HTMLButtonElement
}

interface Crac {
  group: THREE.Group
  fan: THREE.Group
  base: Spot
  angle: number
  band: THREE.MeshStandardMaterial
  display: THREE.MeshStandardMaterial
}

interface Duct {
  from: string
  path: THREE.CurvePath<THREE.Vector3>
  particles: THREE.InstancedMesh
  offset: number
}

interface Led {
  color: THREE.Color
  speed: number
  phase: number
}

function standard(color: number, roughness = 0.6, metalness = 0.15): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness })
}

function solid(geometry: THREE.BufferGeometry, material: THREE.Material): THREE.Mesh {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = true
  mesh.receiveShadow = true
  return mesh
}

function box(w: number, h: number, d: number, material: THREE.Material): THREE.Mesh {
  return solid(new THREE.BoxGeometry(w, h, d), material)
}

/** Piso elevado: placas com tons levemente diferentes e juntas escuras. */
function tileTexture(): THREE.CanvasTexture {
  const size = 512
  const tiles = 4
  const step = size / tiles
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const context = canvas.getContext('2d')
  if (context) {
    for (let row = 0; row < tiles; row += 1) {
      for (let col = 0; col < tiles; col += 1) {
        const shade = 62 + Math.floor(Math.random() * 12)
        context.fillStyle = `rgb(${shade}, ${shade + 1}, ${shade + 3})`
        context.fillRect(col * step, row * step, step, step)
        context.strokeStyle = '#17181a'
        context.lineWidth = 3
        context.strokeRect(col * step + 1.5, row * step + 1.5, step - 3, step - 3)
      }
    }
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

/** Duto em ângulos retos: passa exatamente pelos pontos pedidos, sem ponta solta. */
function ductPath(points: THREE.Vector3[]): THREE.CurvePath<THREE.Vector3> {
  const path = new THREE.CurvePath<THREE.Vector3>()
  points.slice(1).forEach((point, index) => {
    const start = points[index]
    if (start) path.add(new THREE.LineCurve3(start, point))
  })
  return path
}

export function createTwin(canvas: HTMLCanvasElement, data: TwinData, onPick: (id: string | null) => void): Twin {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.15

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(BACKDROP)
  scene.fog = new THREE.Fog(BACKDROP, 28, 64)

  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 120)
  camera.position.copy(HOME_POSITION)

  const controls = new OrbitControls(camera, canvas)
  controls.target.copy(HOME_TARGET)
  controls.enableDamping = true
  controls.maxPolarAngle = Math.PI / 2.08
  controls.minDistance = 4
  controls.maxDistance = 30

  // Brilho: só o que emite luz de verdade (LEDs, telas, marcadores) passa do limiar.
  const composer = new EffectComposer(
    renderer,
    new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 }),
  )
  composer.addPass(new RenderPass(scene, camera))
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.32, 0.35, 1)
  composer.addPass(bloom)
  composer.addPass(new OutputPass())

  // Etiquetas em HTML por cima do canvas: ficam nítidas em qualquer zoom e são clicáveis.
  const labels = new CSS2DRenderer()
  labels.domElement.className = 'twin-labels'
  canvas.insertAdjacentElement('afterend', labels.domElement)

  const pickable: THREE.Object3D[] = []
  const clickable = (object: THREE.Object3D, id: string): void => {
    object.userData.id = id
    pickable.push(object)
  }

  // ------------------------------------------------------------ sala
  const floorTexture = tileTexture()
  floorTexture.repeat.set(ROOM.width / 2.4, ROOM.depth / 2.4)
  floorTexture.anisotropy = renderer.capabilities.getMaxAnisotropy()
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(ROOM.width, ROOM.depth),
    new THREE.MeshStandardMaterial({ map: floorTexture, roughness: 0.42, metalness: 0.25 }),
  )
  floor.rotation.x = -Math.PI / 2
  floor.receiveShadow = true
  scene.add(floor)

  const wallMaterial = standard(0x55585e, 0.92, 0)
  const stripMaterial = new THREE.MeshStandardMaterial({ color: 0x08090a, emissive: ACCENT, emissiveIntensity: 0 })
  const addWall = (width: number, x: number, z: number, rotation: number): void => {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(width, ROOM.height), wallMaterial)
    wall.position.set(x, ROOM.height / 2, z)
    wall.rotation.y = rotation
    wall.receiveShadow = true
    scene.add(wall)
    // Fio de luz no rodapé: fica fraco quando a sala está sem dados.
    const strip = new THREE.Mesh(new THREE.BoxGeometry(width, 0.03, 0.02), stripMaterial)
    strip.position.set(0, -ROOM.height / 2 + 0.12, 0.02)
    wall.add(strip)
  }
  addWall(ROOM.width, 0, -ROOM.depth / 2, 0)
  addWall(ROOM.depth, -ROOM.width / 2, 0, Math.PI / 2)
  addWall(ROOM.depth, ROOM.width / 2, 0, -Math.PI / 2)

  // Janela: a cor do céu vem da luminosidade medida.
  const sky = new THREE.Mesh(
    new THREE.PlaneGeometry(4, 1.8),
    new THREE.MeshBasicMaterial({ color: 0x06090f }),
  )
  sky.position.set(-0.6, 2.7, -ROOM.depth / 2 + 0.03)
  scene.add(sky)
  const frameMaterial = standard(0x121315, 0.5, 0.6)
  for (const [w, h, x, y] of [
    [4.24, 0.1, 0, 0.95],
    [4.24, 0.1, 0, -0.95],
    [0.1, 2, -2.07, 0],
    [0.1, 2, 2.07, 0],
    [0.06, 1.8, -0.67, 0],
    [0.06, 1.8, 0.67, 0],
  ] as const) {
    const bar = box(w, h, 0.08, frameMaterial)
    bar.position.set(-0.6 + x, 2.7 + y, -ROOM.depth / 2 + 0.05)
    scene.add(bar)
  }

  // ------------------------------------------------------------ luzes
  const ambient = new THREE.AmbientLight(0xdfe6f0, 0.5)
  scene.add(ambient)
  scene.add(new THREE.HemisphereLight(0xe8eef8, 0x202226, 0.7))

  // Luz de serviço: dá as sombras e fica fraca quando não há dados.
  const service = new THREE.SpotLight(0xe6edff, 0, 46, 0.95, 0.7, 1.15)
  service.position.set(-3.5, 9.5, 8.5)
  service.target.position.set(0.5, 0, -1)
  service.castShadow = true
  service.shadow.mapSize.set(2048, 2048)
  service.shadow.bias = -0.0004
  scene.add(service, service.target)

  const sun = new THREE.DirectionalLight(0xfff0d2, 0)
  sun.position.set(-0.6, 5, -9)
  sun.target.position.set(0, 0, 3)
  scene.add(sun, sun.target)

  const lampSpot = POSITIONS['light-sala'] as Spot
  const lampMaterial = new THREE.MeshStandardMaterial({ color: 0x1a1b1d, emissive: 0xfff2d6, emissiveIntensity: 0 })
  const lamps: THREE.PointLight[] = []
  for (const offset of [-3.4, 3.4]) {
    const panel = box(2.6, 0.06, 0.55, lampMaterial)
    panel.castShadow = false
    panel.position.set(lampSpot.x + offset, lampSpot.y, lampSpot.z)
    clickable(panel, 'light-sala')
    scene.add(panel)
    const light = new THREE.PointLight(0xfff3dc, 0, 22, 1.3)
    light.position.set(lampSpot.x + offset, lampSpot.y - 0.35, lampSpot.z)
    scene.add(light)
    lamps.push(light)
  }

  // Corredor frio na frente dos racks e ar quente em cima: a força segue os dados.
  const aisle = new THREE.PointLight(0x35e0c8, 0, 8, 1.5)
  aisle.position.set(-0.3, 1.1, 2.4)
  scene.add(aisle)
  const hot = new THREE.PointLight(0xff5a2a, 0, 7, 1.5)
  hot.position.set(-0.3, RACK_SIZE.height + 0.9, 0.4)
  scene.add(hot)

  // ------------------------------------------------------------ racks
  const rackBody = standard(0x121316, 0.38, 0.7)
  const serverFace = standard(0x1d1f23, 0.5, 0.5)
  const glass = new THREE.MeshStandardMaterial({
    color: 0x9ec9ff,
    transparent: true,
    opacity: 0.1,
    roughness: 0.08,
    metalness: 0.4,
    depthWrite: false,
  })
  const padMaterial = new THREE.MeshBasicMaterial({
    color: 0x35e0c8,
    transparent: true,
    opacity: 0,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })

  const allRacks = [...RACKS, ...FILLER_RACKS_X.map((x) => ({ x, z: RACKS[0].z }))]
  const leds: Led[] = []
  const ledMesh = new THREE.InstancedMesh(
    new THREE.BoxGeometry(0.05, 0.035, 0.02),
    new THREE.MeshBasicMaterial({ toneMapped: false }),
    allRacks.length * SERVER_UNITS * LEDS_PER_UNIT,
  )
  ledMesh.frustumCulled = false
  const helper = new THREE.Object3D()
  const LED_PALETTE = [0x2ed0ba, 0x2ed0ba, 0x5aa8ff, 0xf6b53f]

  allRacks.forEach((rack, rackIndex) => {
    const group = new THREE.Group()
    group.position.set(rack.x, 0, rack.z)
    const front = RACK_SIZE.depth / 2

    const body = solid(new RoundedBoxGeometry(RACK_SIZE.width, RACK_SIZE.height, RACK_SIZE.depth, 3, 0.03), rackBody)
    body.position.y = RACK_SIZE.height / 2
    group.add(body)
    const cap = box(RACK_SIZE.width - 0.2, 0.05, RACK_SIZE.depth - 0.2, standard(0x08090a, 0.8, 0.2))
    cap.position.y = RACK_SIZE.height + 0.02
    group.add(cap)
    const door = new THREE.Mesh(new THREE.PlaneGeometry(RACK_SIZE.width - 0.12, RACK_SIZE.height - 0.14), glass)
    door.position.set(0, RACK_SIZE.height / 2, front + 0.045)
    group.add(door)

    for (let unit = 0; unit < SERVER_UNITS; unit += 1) {
      const y = 0.3 + unit * 0.235
      const server = box(RACK_SIZE.width - 0.22, 0.19, 0.03, serverFace)
      server.castShadow = false
      server.position.set(0, y, front + 0.012)
      group.add(server)
      for (let slot = 0; slot < LEDS_PER_UNIT; slot += 1) {
        const index = (rackIndex * SERVER_UNITS + unit) * LEDS_PER_UNIT + slot
        helper.position.set(rack.x + 0.36 + slot * 0.09, y, rack.z + front + 0.034)
        helper.rotation.set(0, 0, 0)
        helper.scale.setScalar(1)
        helper.updateMatrix()
        ledMesh.setMatrixAt(index, helper.matrix)
        ledMesh.setColorAt(index, new THREE.Color(0x000000))
        leds.push({
          color: new THREE.Color(LED_PALETTE[(unit + slot * 2 + rackIndex) % LED_PALETTE.length]),
          speed: 1.5 + ((unit * 7 + slot * 13 + rackIndex * 5) % 9) * 0.55,
          phase: (unit * 1.7 + slot * 2.9 + rackIndex) % 6.28,
        })
      }
    }
    scene.add(group)

    // Placa perfurada do corredor frio, na frente de cada rack.
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(RACK_SIZE.width, 1.1), padMaterial)
    pad.rotation.x = -Math.PI / 2
    pad.position.set(rack.x, 0.012, rack.z + front + 0.7)
    scene.add(pad)
  })
  scene.add(ledMesh)

  // ------------------------------------------------------------ CRACs
  const cracBody = standard(0xaeb4bc, 0.5, 0.3)
  const darkMetal = standard(0x101113, 0.5, 0.6)
  const bladeMaterial = standard(0xaeb4bb, 0.35, 0.7)
  const cracs = new Map<string, Crac>()

  for (const id of ['crac-01', 'crac-02']) {
    const spot = POSITIONS[id] as Spot
    const group = new THREE.Group()
    group.position.set(spot.x, 0, spot.z)

    const body = solid(new RoundedBoxGeometry(2.2, 2.5, 1.3, 4, 0.07), cracBody)
    body.position.y = 1.25
    clickable(body, id)
    group.add(body)

    const recess = solid(new THREE.CylinderGeometry(0.62, 0.62, 0.05, 40), darkMetal)
    recess.rotation.x = Math.PI / 2
    recess.position.set(-0.25, 1.55, 0.655)
    group.add(recess)
    const guard = solid(new THREE.TorusGeometry(0.62, 0.035, 10, 48), bladeMaterial)
    guard.position.set(-0.25, 1.55, 0.69)
    group.add(guard)

    const fan = new THREE.Group()
    fan.position.set(-0.25, 1.55, 0.7)
    for (let blade = 0; blade < 5; blade += 1) {
      const wing = box(0.46, 0.16, 0.02, bladeMaterial)
      wing.castShadow = false
      wing.position.x = 0.3
      wing.rotation.x = 0.35
      const arm = new THREE.Group()
      arm.rotation.z = (blade * 2 * Math.PI) / 5
      arm.add(wing)
      fan.add(arm)
    }
    const hub = solid(new THREE.CylinderGeometry(0.1, 0.1, 0.06, 20), darkMetal)
    hub.rotation.x = Math.PI / 2
    fan.add(hub)
    group.add(fan)

    for (let slat = 0; slat < 5; slat += 1) {
      const bar = box(1.8, 0.05, 0.03, darkMetal)
      bar.castShadow = false
      bar.position.set(0, 0.22 + slat * 0.11, 0.662)
      group.add(bar)
    }

    // Tela e faixa do topo: acendem na cor do estado da máquina.
    const display = new THREE.MeshStandardMaterial({ color: 0x050506, emissive: STATUS_COLOR.offline })
    const screen = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.26, 0.02), display)
    screen.position.set(0.72, 1.95, 0.66)
    group.add(screen)
    const band = new THREE.MeshStandardMaterial({ color: 0x050506, emissive: STATUS_COLOR.offline })
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(2.22, 0.05, 1.32), band)
    stripe.position.y = 2.36
    group.add(stripe)

    const collar = solid(new THREE.CylinderGeometry(0.22, 0.22, 0.16, 24), darkMetal)
    collar.position.y = 2.56
    group.add(collar)

    scene.add(group)
    cracs.set(id, { group, fan, base: spot, angle: 0, band, display })
  }

  // ------------------------------------------------------------ dutos
  // Translúcidos, para o ar em movimento aparecer por dentro.
  const ductMaterial = new THREE.MeshStandardMaterial({
    color: 0xcfe2f2,
    transparent: true,
    opacity: 0.2,
    roughness: 0.15,
    metalness: 0.3,
    depthWrite: false,
  })
  const jointMaterial = standard(0x8c949c, 0.3, 0.85)
  const airMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(0x8fe3ff).multiplyScalar(1.15),
    opacity: 0.8,
    toneMapped: false,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
  const airGeometry = new THREE.SphereGeometry(0.03, 8, 8)
  const ducts: Duct[] = []

  const routeDuct = (from: string, target: number): void => {
    const spot = POSITIONS[from] as Spot
    const rack = RACKS[target]
    if (!rack) return
    const height = 3.35
    const points = [
      new THREE.Vector3(spot.x, 2.64, spot.z),
      new THREE.Vector3(spot.x, height, spot.z),
      new THREE.Vector3(spot.x, height, rack.z),
      new THREE.Vector3(rack.x, height, rack.z),
      new THREE.Vector3(rack.x, RACK_SIZE.height + 0.04, rack.z),
    ]
    const path = ductPath(points)
    for (const curve of path.curves) {
      scene.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 1, 0.16, 16), ductMaterial))
    }
    points.forEach((point, index) => {
      const end = index === 0 || index === points.length - 1
      const joint = end
        ? solid(new THREE.CylinderGeometry(0.21, 0.21, 0.08, 24), jointMaterial)
        : solid(new THREE.SphereGeometry(0.19, 20, 20), jointMaterial)
      joint.position.copy(point)
      scene.add(joint)
    })
    const particles = new THREE.InstancedMesh(airGeometry, airMaterial, AIR_PER_DUCT)
    particles.frustumCulled = false
    scene.add(particles)
    ducts.push({ from, path, particles, offset: 0 })
  }
  routeDuct('crac-01', 0)
  routeDuct('crac-02', 1)

  // Ar quente sobre os racks: quanto mais quente a sala, mais partículas sobem.
  const heat = new THREE.InstancedMesh(
    new THREE.SphereGeometry(0.06, 8, 8),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(0xff6a3c).multiplyScalar(1.4),
      toneMapped: false,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
    HEAT_PARTICLES,
  )
  heat.frustumCulled = false
  scene.add(heat)
  const heatSeeds = Array.from({ length: HEAT_PARTICLES }, (_, index) => ({
    x: (Math.random() - 0.5) * RACK_SIZE.width * 0.85 + (RACKS[index % RACKS.length]?.x ?? 0),
    z: (Math.random() - 0.5) * RACK_SIZE.depth * 0.8 + RACKS[0].z,
    phase: Math.random(),
  }))

  // ------------------------------------------------------------ atuadores
  const exhaustSpot = POSITIONS['fan-exaustor'] as Spot
  const exhaustGroup = new THREE.Group()
  exhaustGroup.position.set(exhaustSpot.x - 0.06, exhaustSpot.y, exhaustSpot.z)
  exhaustGroup.rotation.y = -Math.PI / 2
  const housing = box(1.5, 1.5, 0.1, darkMetal)
  clickable(housing, 'fan-exaustor')
  exhaustGroup.add(housing)
  const exhaustRing = solid(new THREE.TorusGeometry(0.62, 0.04, 10, 44), bladeMaterial)
  exhaustRing.position.z = 0.08
  exhaustGroup.add(exhaustRing)
  const exhaust = new THREE.Group()
  exhaust.position.z = 0.09
  for (let blade = 0; blade < 4; blade += 1) {
    const wing = box(0.5, 0.17, 0.02, bladeMaterial)
    wing.position.x = 0.3
    wing.rotation.x = 0.4
    const arm = new THREE.Group()
    arm.rotation.z = (blade * Math.PI) / 2
    arm.add(wing)
    exhaust.add(arm)
  }
  exhaustGroup.add(exhaust)
  scene.add(exhaustGroup)

  const sirenSpot = POSITIONS['siren-sala'] as Spot
  const sirenMaterial = new THREE.MeshStandardMaterial({ color: 0x3a0d08, emissive: 0xff2a1a, emissiveIntensity: 0 })
  const sirenBase = solid(new THREE.CylinderGeometry(0.2, 0.2, 0.1, 24), darkMetal)
  sirenBase.rotation.z = Math.PI / 2
  sirenBase.position.set(sirenSpot.x + 0.06, sirenSpot.y, sirenSpot.z)
  scene.add(sirenBase)
  const siren = new THREE.Mesh(new THREE.SphereGeometry(0.17, 24, 16), sirenMaterial)
  siren.position.set(sirenSpot.x + 0.17, sirenSpot.y, sirenSpot.z)
  clickable(siren, 'siren-sala')
  scene.add(siren)
  const sirenLight = new THREE.PointLight(0xff2a1a, 0, 10, 1.5)
  sirenLight.position.copy(siren.position)
  scene.add(sirenLight)

  // Porta: gira na dobradiça quando o sensor de presença dispara.
  const doorSpot = POSITIONS['door-sala'] as Spot
  const doorFrame = standard(0x16171a, 0.5, 0.5)
  for (const z of [doorSpot.z - 0.62, doorSpot.z + 0.62]) {
    const post = box(0.1, 2.3, 0.1, doorFrame)
    post.position.set(ROOM.width / 2 - 0.05, 1.15, z)
    scene.add(post)
  }
  const lintel = box(0.1, 0.1, 1.34, doorFrame)
  lintel.position.set(ROOM.width / 2 - 0.05, 2.3, doorSpot.z)
  scene.add(lintel)
  const hinge = new THREE.Group()
  hinge.position.set(ROOM.width / 2 - 0.06, 0, doorSpot.z - 0.57)
  const leaf = box(0.06, 2.2, 1.14, standard(0x3a3e45, 0.55, 0.4))
  leaf.position.set(0, 1.12, 0.57)
  clickable(leaf, 'door-sala')
  hinge.add(leaf)
  scene.add(hinge)

  // ------------------------------------------------------------ marcadores
  const items = new Map<string, Item>()
  const markerGeometry = new THREE.SphereGeometry(0.1, 20, 20)
  const ringGeometry = new THREE.RingGeometry(0.17, 0.215, 36)
  const puckGeometry = new RoundedBoxGeometry(0.26, 0.16, 0.07, 2, 0.02)
  const puckMaterial = standard(0xe4e7ea, 0.5, 0.2)
  let selected: string | null = null
  let live = false

  function addItem(device: Device, spot: Spot): void {
    const marker = new THREE.Mesh(
      markerGeometry,
      new THREE.MeshBasicMaterial({ color: STATUS_COLOR.offline, toneMapped: false }),
    )
    marker.position.set(spot.x, device.kind === 'equipment' ? spot.y + 1.75 : spot.y, spot.z)
    clickable(marker, device.id)

    if (device.kind === 'sensor') {
      // Caixinha do sensor: o marcador é o LED dela.
      const puck = solid(puckGeometry, puckMaterial)
      puck.position.z = -0.06
      marker.add(puck)
    }

    const ring = new THREE.Mesh(
      ringGeometry,
      new THREE.MeshBasicMaterial({
        color: 0xffffff,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0,
        toneMapped: false,
        depthTest: false,
      }),
    )
    ring.position.copy(marker.position)

    const element = document.createElement('button')
    element.type = 'button'
    element.className = 'twin-label'
    element.dataset.status = 'offline'
    element.setAttribute('aria-pressed', 'false')
    element.setAttribute('aria-label', `Abrir painel de ${device.name}`)
    element.append(document.createElement('i'), device.id)
    element.addEventListener('click', () => onPick(device.id))
    const label = new CSS2DObject(element)
    label.center.set(0.5, 1.75)
    marker.add(label)

    scene.add(marker, ring)
    items.set(device.id, { id: device.id, marker, ring, label, element })
  }

  function removeItem(item: Item): void {
    item.marker.remove(item.label)
    item.element.remove()
    scene.remove(item.marker, item.ring)
    pickable.splice(pickable.indexOf(item.marker), 1)
    items.delete(item.id)
  }

  function syncItems(): void {
    const devices = data.devices()
    const ids = new Set(devices.map((device) => device.id))
    for (const item of [...items.values()]) {
      if (!ids.has(item.id)) removeItem(item)
    }
    let shelf = 0
    for (const device of devices) {
      const known = POSITIONS[device.id]
      const spot = known ?? shelfSpot(shelf)
      if (!known) shelf += 1
      if (!items.has(device.id)) addItem(device, spot)
    }
    live = devices.some((device) => data.metrics(device.id) !== undefined)
  }

  // ------------------------------------------------------------ interação
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let downAt = { x: 0, y: 0 }
  let idle = !reducedMotion

  function hitAt(event: PointerEvent): string | null {
    const rect = canvas.getBoundingClientRect()
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObjects(pickable, false)[0]
    return hit ? (hit.object.userData.id as string) : null
  }

  function onDown(event: PointerEvent): void {
    downAt = { x: event.clientX, y: event.clientY }
  }

  function onUp(event: PointerEvent): void {
    // Arrastar gira a câmera; só clique parado seleciona.
    if (Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 5) return
    onPick(hitAt(event))
  }

  function onMove(event: PointerEvent): void {
    if (event.buttons === 0) canvas.style.cursor = hitAt(event) ? 'pointer' : 'grab'
  }

  const stopIdle = (): void => {
    idle = false
  }

  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('pointerup', onUp)
  canvas.addEventListener('pointermove', onMove)
  controls.addEventListener('start', stopIdle)

  const resize = new ResizeObserver(() => {
    const { clientWidth: width, clientHeight: height } = canvas
    if (width === 0 || height === 0) return
    renderer.setSize(width, height, false)
    composer.setPixelRatio(renderer.getPixelRatio())
    composer.setSize(width, height)
    labels.setSize(width, height)
    camera.aspect = width / height
    // Em telas estreitas a câmera recua, para a sala inteira caber.
    camera.fov = width / height < 1.2 ? 56 : 40
    camera.updateProjectionMatrix()
  })
  resize.observe(canvas)

  // ------------------------------------------------------------ animação
  const skyNight = new THREE.Color(0x06090f)
  const skyDay = new THREE.Color(0x9fd6f5)
  const tint = new THREE.Color()
  const focus = new THREE.Vector3()
  const clock = new THREE.Clock()
  const swayRadius = Math.hypot(HOME_POSITION.x - HOME_TARGET.x, HOME_POSITION.z - HOME_TARGET.z)
  const swayAngle = Math.atan2(HOME_POSITION.x - HOME_TARGET.x, HOME_POSITION.z - HOME_TARGET.z)
  let frameId = 0
  let exhaustAngle = 0
  let lastSync = -1
  let power = 0
  let doorOpen = 0

  function isOn(id: string): boolean {
    return data.metrics(id)?.on === 1
  }

  function animate(): void {
    frameId = requestAnimationFrame(animate)
    const delta = Math.min(clock.getDelta(), 0.1)
    const time = clock.elapsedTime
    const ease = Math.min(1, delta * 3)

    if (time - lastSync > 1) {
      syncItems()
      lastSync = time
    }

    // Sem dados a sala "desliga": luz de serviço e rodapé caem para o mínimo.
    power += ((live ? 1 : 0) - power) * ease
    stripMaterial.emissiveIntensity = 0.1 + 0.75 * power

    // Dia e noite pela luminosidade real, descontando a lâmpada.
    const lampOn = isOn('light-sala')
    const lux = data.metrics('lux-sala')?.luminosity
    const day = lux === undefined ? 0 : THREE.MathUtils.clamp((lux - (lampOn ? LAMP_LUX : 0)) / DAYLIGHT_LUX, 0, 1)
    ;(sky.material as THREE.MeshBasicMaterial).color.copy(skyNight).lerp(skyDay, day)
    sun.intensity = day * 1.1
    ambient.intensity = 0.45 + day * 0.2
    lampMaterial.emissiveIntensity += ((lampOn ? 1.2 : 0) - lampMaterial.emissiveIntensity) * ease
    const lampLevel = lampMaterial.emissiveIntensity / 1.2
    for (const light of lamps) light.intensity = lampLevel * 7
    // A luz de serviço recua quando o dia ou a lâmpada já iluminam a sala.
    service.intensity = (30 + 100 * power) * (1 - 0.35 * day) * (1 - 0.3 * lampLevel)

    // Racks: cada LED pisca no seu ritmo, mais rápido com mais corrente.
    const current = data.metrics('pwr-rack01')?.current
    const activity = current === undefined ? 0 : THREE.MathUtils.clamp(current / 14, 0.5, 1.8)
    leds.forEach((led, index) => {
      const lit = activity > 0 && Math.sin(time * led.speed * activity + led.phase) > -0.25
      tint.copy(led.color).multiplyScalar(activity === 0 ? 0 : lit ? 1.8 : 0.2)
      ledMesh.setColorAt(index, tint)
    })
    if (ledMesh.instanceColor) ledMesh.instanceColor.needsUpdate = true
    aisle.intensity = current === undefined ? 0 : 1.5 + current * 0.15
    padMaterial.opacity = current === undefined ? 0 : 0.035 + 0.015 * Math.sin(time * 1.5)

    // CRACs: giro pela rotação medida, tremor pela vibração medida.
    for (const [id, unit] of cracs) {
      const metrics = data.metrics(id)
      const rpm = metrics?.rpm ?? 0
      unit.angle += (rpm / 1450) * delta * 14
      unit.fan.rotation.z = unit.angle
      const vibration = metrics?.vibration ?? 0
      const shake = rpm > 0 ? Math.max(0, vibration - 2) * 0.012 : 0
      unit.group.position.x = unit.base.x + Math.sin(time * 61) * shake
      unit.group.position.z = unit.base.z + Math.cos(time * 53) * shake

      const status = data.status(id)
      const glow = status === 'offline' ? 0.3 : status === 'critical' ? 1.9 + Math.sin(time * 6) * 0.7 : 1.4
      unit.band.emissive.setHex(STATUS_COLOR[status])
      unit.display.emissive.setHex(STATUS_COLOR[status])
      unit.band.emissiveIntensity = unit.display.emissiveIntensity = glow
    }

    // Ar nos dutos: só corre com o CRAC girando.
    for (const duct of ducts) {
      const rpm = data.metrics(duct.from)?.rpm ?? 0
      duct.offset = (duct.offset + delta * 0.14 * (rpm / 1450)) % 1
      for (let index = 0; index < AIR_PER_DUCT; index += 1) {
        if (rpm > 0) {
          const fraction = (index / AIR_PER_DUCT + duct.offset) % 1
          helper.position.copy(duct.path.getPointAt(fraction))
          helper.position.x += Math.sin(index * 12.9) * 0.06
          helper.position.z += Math.cos(index * 7.3) * 0.06
          helper.scale.setScalar(0.7 + 0.5 * Math.abs(Math.sin(index * 3.1)))
        } else {
          helper.scale.setScalar(0)
        }
        helper.updateMatrix()
        duct.particles.setMatrixAt(index, helper.matrix)
      }
      duct.particles.instanceMatrix.needsUpdate = true
    }

    // Ar quente: nasce acima de 28 °C e fica cheio perto de 38 °C.
    const temperature = data.temperature()
    const warmth = temperature === undefined ? 0 : THREE.MathUtils.clamp((temperature - 28) / 10, 0, 1)
    hot.intensity = warmth * 14
    heatSeeds.forEach((seed, index) => {
      const visible = index / HEAT_PARTICLES < warmth
      const rise = (seed.phase + time * 0.18) % 1
      helper.position.set(seed.x + Math.sin(time + index) * 0.05, RACK_SIZE.height + 0.1 + rise * 1.5, seed.z)
      helper.scale.setScalar(visible ? 1.3 - rise : 0)
      helper.updateMatrix()
      heat.setMatrixAt(index, helper.matrix)
    })
    heat.instanceMatrix.needsUpdate = true

    if (isOn('fan-exaustor')) exhaustAngle += delta * 12
    exhaust.rotation.z = exhaustAngle

    const pulse = isOn('siren-sala') ? (Math.sin(time * 9) + 1) / 2 : 0
    sirenMaterial.emissiveIntensity = pulse * 4
    sirenLight.intensity = pulse * 26

    doorOpen += ((data.metrics('door-sala')?.presence === 1 ? 1 : 0) - doorOpen) * ease
    hinge.rotation.y = -1.1 * doorOpen

    for (const item of items.values()) {
      const status = data.status(item.id)
      const material = item.marker.material as THREE.MeshBasicMaterial
      material.color.setHex(STATUS_COLOR[status]).multiplyScalar(status === 'offline' ? 0.8 : 1.5)
      if (item.element.dataset.status !== status) item.element.dataset.status = status

      // O anel marca o item selecionado e pulsa em quem está fora do normal.
      const alarmed = status === 'critical' || status === 'warning'
      const beat = (time * (status === 'critical' ? 1.6 : 0.8)) % 1
      const ring = item.ring.material as THREE.MeshBasicMaterial
      ring.color.setHex(item.id === selected ? 0xffffff : STATUS_COLOR[status])
      ring.opacity = item.id === selected ? 0.95 : alarmed ? 0.8 * (1 - beat) : 0
      item.ring.scale.setScalar(item.id === selected || !alarmed ? 1 : 1 + beat * 1.8)
      item.ring.lookAt(camera.position)
    }

    // A câmera se inclina de leve para o item selecionado; sem seleção, volta para a sala.
    const chosen = selected ? items.get(selected) : undefined
    focus.copy(HOME_TARGET)
    if (chosen) focus.lerp(chosen.marker.position, 0.3)
    controls.target.lerp(focus, Math.min(1, delta * 2.5))
    if (idle && !selected) {
      // Balanço lento até a primeira interação, para a sala não parecer uma foto.
      const angle = swayAngle + Math.sin(time * 0.13) * 0.32
      camera.position.set(
        HOME_TARGET.x + Math.sin(angle) * swayRadius,
        HOME_POSITION.y,
        HOME_TARGET.z + Math.cos(angle) * swayRadius,
      )
    }

    controls.update()
    composer.render(delta)
    labels.render(scene, camera)
  }
  animate()

  return {
    select(id) {
      selected = id
      if (id) idle = false
      for (const item of items.values()) {
        item.element.setAttribute('aria-pressed', String(item.id === id))
      }
    },
    dispose() {
      cancelAnimationFrame(frameId)
      resize.disconnect()
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointermove', onMove)
      controls.removeEventListener('start', stopIdle)
      controls.dispose()
      labels.domElement.remove()
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh
        mesh.geometry?.dispose()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((entry) => entry.dispose())
        else material?.dispose()
      })
      floorTexture.dispose()
      composer.dispose()
      renderer.dispose()
    },
  }
}
