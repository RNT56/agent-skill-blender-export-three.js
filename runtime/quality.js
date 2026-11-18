// Adaptive resolution: keeps the frame rate near a target by scaling the render resolution (pixel ratio).
export class AdaptiveResolution {
  constructor(renderer, { min = 0.6, max = Math.min(devicePixelRatio || 1, 2), target = 48, start = null, onChange = null } = {}) {
    this.r = renderer; this.onChange = onChange; this.min = min; this.max = max; this.target = target;
    this.ratio = start ?? Math.min(max, 1.5);
    this._acc = 0; this._frames = 0; this._hold = 0;
    renderer.setPixelRatio(this.ratio);
  }
  /** call once per frame with the frame time in seconds */
  tick(dt) {
    this._acc += dt; this._frames++;
    if (this._acc < 1.0) return;
    const fps = this._frames / this._acc;
    this._acc = 0; this._frames = 0;
    if (this._hold > 0) { this._hold--; return; }
    let nr = this.ratio;
    if (fps < this.target * 0.85) nr = Math.max(this.min, this.ratio - 0.15);
    else if (fps > this.target * 1.3) nr = Math.min(this.max, this.ratio + 0.1);
    if (Math.abs(nr - this.ratio) > 1e-3) { this.ratio = nr; this.r.setPixelRatio(nr); this.onChange?.(nr); this._hold = 2; }
    this.fps = fps;
  }
}
