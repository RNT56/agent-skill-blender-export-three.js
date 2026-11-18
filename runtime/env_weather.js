// Weather: a small state machine other systems read. The atmosphere dims and greys the light with cloud cover, thickens the fog, and a future
// precipitation system (rain, snow, storms) will read `precip` / `lightning` without any change to the atmosphere or the lighting rig.
//
//   cloud   0 clear .. 1 overcast        mist   extra low fog 0..1        precip 0..1 (reserved)       wind  speed multiplier 0..2
const clamp01 = v => Math.min(1, Math.max(0, v));

export class Weather {
  constructor({ cloud = 0.3, mist = 0.1, wind = 1 } = {}) {
    this.cloud = cloud; this.mist = mist; this.precip = 0; this.lightning = 0; this.wind = wind;
    this.target = { cloud, mist, wind }; this.auto = true;
  }
  /** ease toward a target; set auto = false to hold the weather still */
  setTarget(t) { Object.assign(this.target, t); this.auto = false; }
  update(dt, t) {
    if (this.auto) {                                                         // slow natural drift: banks of cloud come and go over ~10 minutes
      this.target.cloud = clamp01(0.32 + 0.3 * Math.sin(t * 0.0105 + 1.3) + 0.18 * Math.sin(t * 0.0371 + 4.0));
      this.target.mist = clamp01(0.12 + 0.12 * Math.sin(t * 0.0047 + 2.0));
      this.target.wind = 0.85 + 0.35 * Math.sin(t * 0.021) * Math.sin(t * 0.0083 + 1);
    }
    const k = 1 - Math.exp(-dt * 0.25);
    this.cloud += (this.target.cloud - this.cloud) * k; this.mist += (this.target.mist - this.mist) * k; this.wind += (this.target.wind - this.wind) * k;
  }
}
