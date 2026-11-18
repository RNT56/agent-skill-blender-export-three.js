// World clock + celestial mechanics. Pure (no three.js): the same code runs in the browser, in node tests and in offline tools.
//
//   hour   0..24 local solar time            day     whole days elapsed
//   season continuous 0..4: 0 = spring equinox, 1 = summer solstice, 2 = autumn equinox, 3 = winter solstice (northern hemisphere)
//
// Sun elevation follows the real formula for the configured latitude and the season's declination, so autumn noon is low and golden and
// winter days are short, without any hand-tuned curves.

const DEG = Math.PI / 180;

/** sun declination (degrees) for a continuous season value */
export function declination(season) { return 23.44 * Math.sin(Math.PI * season / 2); }

/**
 * @returns {{ elevation: number, azimuth: number }} degrees; azimuth clockwise from NORTH, 180 = due south
 */
export function sunPosition(hour, season, latitude = 35.5) {
  const phi = latitude * DEG, dec = declination(season) * DEG, H = (hour - 12) * 15 * DEG;
  const sinEl = Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H);
  const el = Math.asin(Math.max(-1, Math.min(1, sinEl)));
  // azimuth from north: atan2(sin H, cos H sin phi - tan dec cos phi) + 180
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi)) / DEG + 180;
  return { elevation: el / DEG, azimuth: ((az % 360) + 360) % 360 };
}

/** direction TOWARD a body as [x, y, z] in the game's frame: +x east, +y up, -z north (so due south is +z) */
export function directionOf(elevationDeg, azimuthDeg) {
  const el = elevationDeg * DEG, az = azimuthDeg * DEG;
  return [Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)];
}

/**
 * Moon: treated as a second "sun" that transits `phase * 24` hours after noon (new moon with the sun, first quarter at sunset, full at midnight)
 * and sits `phase * 4` season-units further along the ecliptic (half a year ahead at full moon: a high winter moon, a low summer one).
 * phase: 0 = new, 0.25 = first quarter, 0.5 = full. A synodic month is ~29.5 world days.
 */
export function moonState(hour, dayCount, season, latitude = 35.5) {
  const phase = ((dayCount / 29.53) % 1 + 1) % 1;
  const p = sunPosition(hour - phase * 24, season + phase * 4, latitude);
  return { elevation: p.elevation, azimuth: p.azimuth, phase };
}

export class WorldClock {
  /**
   * @param hour          starting local solar time
   * @param season        starting season value (2.45 = autumn)
   * @param dayLength     real seconds per world day
   * @param seasonDays    world days per season (a year = 4 x seasonDays)
   * @param moonAge       age of the moon in days at the start (0 = new, 14.8 = full): the default starts a day or two before full, so the first night is lit
   */
  constructor({ hour = 9.5, season = 2.45, dayLength = 900, seasonDays = 4, latitude = 35.5, day = 0, moonAge = 12.5 } = {}) {
    Object.assign(this, { hour, dayLength, seasonDays, latitude, day, moonAge });
    this.season0 = season; this.elapsedDays = 0;                          // days elapsed since the start (fractional)
    this.timeScale = 1; this.paused = false;
  }

  /** advance by real seconds */
  update(dt) {
    if (this.paused || this.timeScale === 0) return;
    const days = dt * this.timeScale / this.dayLength;
    this.elapsedDays += days;
    this.hour += days * 24;
    while (this.hour >= 24) { this.hour -= 24; this.day++; }
  }

  /** continuous season value in [0, 4) */
  get season() { return (((this.season0 + this.elapsedDays / this.seasonDays) % 4) + 4) % 4; }
  set season(v) { this.season0 = v - this.elapsedDays / this.seasonDays; }          // elapsedDays also drives the moon: keep it
  setHour(h) { this.hour = ((h % 24) + 24) % 24; }
  get seasonName() { const s = this.season; return s < 0.75 ? 'Spring' : s < 1.75 ? 'Summer' : s < 3.0 ? 'Autumn' : s < 3.9 ? 'Winter' : 'Spring'; }
  get clockText() { const h = Math.floor(this.hour), m = Math.floor((this.hour - h) * 60); return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'); }
  /** human line for the HUD */
  describe() { return `Day ${this.day + 1} · ${this.clockText} · ${this.seasonName}`; }

  sun() { return sunPosition(this.hour, this.season, this.latitude); }
  moon() { return moonState(this.hour, this.moonAge + this.elapsedDays, this.season, this.latitude); }
}
