// Atmosphere: clock + season + weather -> everything the renderer needs this frame (sun, moon, sky colours, ambient, fog, exposure, bloom,
// colour grade, stars, lamps, clouds, seasonal state). Data-driven: looks/atmosphere.json holds keyframes indexed by SUN ELEVATION (night ..
// noon), so day length and twilight follow the astronomy automatically, plus seasonal descriptors that tint and modulate the result.
//
// The returned state is a single shared object (no per-frame allocation); read it, do not keep references to its colours across frames.
import * as THREE from 'three';
import { directionOf } from './env_clock.js';
import { lerpTree, Seasons } from './env_seasons.js';

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const col = () => new THREE.Color();

export class Atmosphere {
  /** @param data parsed looks/atmosphere.json */
  constructor(data) {
    this.data = data;
    this.keys = [...data.keys].sort((a, b) => a.elev - b.elev);
    this.seasons = new Seasons(data.seasons);
    this._k = null;                                                          // shared interpolated keyframe
    this._tmp = new THREE.Vector3();
    this.state = {
      sunDir: new THREE.Vector3(), sunElev: 0, sunColor: col(), sunIntensity: 0,
      moonDir: new THREE.Vector3(), moonElev: -30, moonPhase: 0.5, moonColor: col(), moonIntensity: 0,
      keyDir: new THREE.Vector3(0, 1, 0), keyColor: col(), keyIntensity: 0,
      sky: { top: col(), mid: col(), horizon: col(), glow: col(), ground: col() },
      hemi: { sky: col(), ground: col(), intensity: 1 }, fill: { color: col(), intensity: 0 }, fog: { color: col(), density: 0.006 },
      exposure: 1, bloom: 0.3, grade: null, stars: 0, lamps: 0,
      cloud: { cover: 0.45, lit: col(), shadow: col(), speed: data.clouds?.speed ?? 0.0035, shadowStrength: 0.5 },
      daylight: 1, night: 0, twilight: 0, skyColor: col(),
      season: null, weather: null,
    };
  }

  /** interpolate the keyframes at a sun elevation (degrees) */
  sample(elev) {
    const K = this.keys; let i = 0;
    while (i < K.length - 2 && elev > K[i + 1].elev) i++;
    const a = K[i], b = K[i + 1];
    return (this._k = lerpTree(a, b, smooth(a.elev, b.elev, elev), this._k));
  }

  /**
   * @param clock    WorldClock
   * @param weather  Weather ({cloud, mist, precip})
   * @returns the shared state object
   */
  update(clock, weather) {
    const S = this.state, sun = clock.sun(), moon = clock.moon();
    const k = this.sample(sun.elevation), ssn = this.seasons.at(clock.season), L = ssn.light;
    const cloud = weather?.cloud ?? 0, mist = weather?.mist ?? 0;
    const dayW = smooth(-6, 8, sun.elevation);                               // seasons colour the daytime, not the night
    S.sunElev = sun.elevation; S.moonElev = moon.elevation; S.moonPhase = moon.phase; S.season = ssn; S.weather = weather ?? null;
    S.sunDir.fromArray(directionOf(sun.elevation, sun.azimuth)); S.moonDir.fromArray(directionOf(moon.elevation, moon.azimuth));

    // sun: keyframe colour tinted by the season and dimmed by cloud
    const tint = L.sunTint;
    S.sunColor.setRGB(k.sun.color[0] * (1 + (tint[0] - 1) * dayW), k.sun.color[1] * (1 + (tint[1] - 1) * dayW), k.sun.color[2] * (1 + (tint[2] - 1) * dayW));
    S.sunIntensity = k.sun.intensity * (1 + (L.sunMul - 1) * dayW) * (1 - 0.72 * cloud);

    // moon: only while the sun is down, brighter near full, hidden below the horizon
    const full = 0.5 - 0.5 * Math.cos(2 * Math.PI * moon.phase), night = 1 - smooth(-9, 1, sun.elevation);
    S.moonColor.setRGB(...this.data.moon.color);
    S.moonIntensity = this.data.moon.intensity * night * smooth(-3, 9, moon.elevation) * (0.3 + 0.7 * full) * (1 - 0.6 * cloud);

    // the one shadow-casting key light is the intensity-weighted blend of both, so its direction never jumps at dusk or dawn
    const si = S.sunIntensity, mi = S.moonIntensity, tot = si + mi;
    if (tot > 1e-4) {
      S.keyDir.copy(S.sunDir).multiplyScalar(si).addScaledVector(S.moonDir, mi).normalize();
      const a = si / tot, b = mi / tot;
      S.keyColor.setRGB(S.sunColor.r * a + S.moonColor.r * b, S.sunColor.g * a + S.moonColor.g * b, S.sunColor.b * a + S.moonColor.b * b);
    } else { S.keyDir.copy(S.moonElev > S.sunElev ? S.moonDir : S.sunDir); S.keyColor.copy(S.moonColor); }
    S.keyIntensity = tot;

    // sky: keyframe gradient, greyed by cloud in daylight
    const grey = cloud * 0.55 * dayW, sky = S.sky;
    for (const name of ['top', 'mid', 'horizon', 'glow', 'ground']) {
      const c = k.sky[name], l = (c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11) * (name === 'glow' ? 1 : 0.9);
      sky[name].setRGB(c[0] + (l - c[0]) * grey, c[1] + (l - c[1]) * grey, c[2] + (l - c[2]) * grey);
    }
    S.hemi.sky.setRGB(...k.hemi.sky); S.hemi.ground.setRGB(...k.hemi.ground); S.hemi.intensity = k.hemi.intensity * (1 + 0.18 * cloud);
    S.fill.color.setRGB(...k.fill.color); S.fill.intensity = k.fill.intensity * (1 - 0.35 * cloud);

    // fog: thicker with the season's haze, cloud and mist
    S.fog.color.setRGB(...k.fog.color);
    S.fog.density = k.fog.density * (1 + (L.haze - 1) * dayW) * (1 + 0.6 * cloud + 1.4 * mist);
    S.exposure = k.exposure * (1 + 0.05 * cloud); S.bloom = k.bloom;

    // colour grade: keyframe + season + weather
    const g = (S.grade = lerpTree(k.grade, k.grade, 0, S.grade));
    g.sat = (k.grade.sat + L.sat * dayW) * (1 - 0.2 * cloud);
    g.temp = k.grade.temp + L.temp * dayW; g.contrast = k.grade.contrast + L.contrast * dayW;

    S.stars = k.stars * (1 - 0.85 * cloud); S.lamps = Math.max(k.lamps, smooth(0.6, 1.0, cloud) * 0.3 * dayW);                    // only a gloomy storm sky lights the lanterns by day
    S.cloud.cover = (this.data.clouds?.coverBase ?? 0.42) + 0.45 * cloud;
    S.cloud.lit.setRGB(...k.cloud.lit); S.cloud.shadow.setRGB(...k.cloud.shadow);
    S.cloud.shadowStrength = 0.5 * smooth(2, 14, sun.elevation) * (0.35 + 0.65 * cloud + 0.25 * (1 - dayW));

    S.daylight = smooth(-4, 10, sun.elevation); S.night = 1 - smooth(-12, -2, sun.elevation); S.twilight = Math.max(0, 1 - S.daylight - S.night);
    S.skyColor.copy(sky.horizon).lerp(sky.mid, 0.5);
    return S;
  }
}
