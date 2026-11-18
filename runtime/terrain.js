// Heightfield terrain with N-biome PBR splatting: texture arrays (albedo / normal / ORM), splat maps from a weights callback,
// anti-tiling (second sample at a rotated/rescaled UV, blended by low-frequency noise), derivative-based tangent frame.
// Plus: triplanar rock on steep faces (cliffs are not stretched planar textures), shoreline wetness around a lake, a walkability overlay
// (green/yellow/orange/red by slope, thresholds supplied by the game), and seasonal ground tint + snow cover, all driven by live uniforms.
import * as THREE from 'three';

/** GLSL shared by the terrain and the rock instances (rocks.js): the six rock materials sampled biplanarly from the rock texture arrays (needs `precision highp sampler2DArray`) */
export const ROCK_SAMPLE_GLSL = `
      // ---- rock material sampling: albedo, ORM (b = height) and a world-space normal from a biplanar projection (the two most face-on planes; pow() sharpens the blend)
      uniform sampler2DArray uRAlb, uRNor, uROrm; uniform vec4 uRLayer[2]; uniform vec4 uRTile[2]; uniform vec2 uRockAlt; uniform float uRockOn;
      vec3 rockAlb, rockNrm; vec4 rockOrm;
      vec4 rockSample(int m, vec3 P, vec3 N, vec3 dpx, vec3 dpy){
        float layer = m < 4 ? uRLayer[0][m] : uRLayer[1][m - 4], tile = m < 4 ? uRTile[0][m] : uRTile[1][m - 4];
        vec3 p = P / tile, dx = dpx / tile, dy = dpy / tile, an = abs(N);
        ivec3 ma = (an.x > an.y && an.x > an.z) ? ivec3(0, 1, 2) : (an.y > an.z) ? ivec3(1, 2, 0) : ivec3(2, 0, 1);
        ivec3 mi = (an.x < an.y && an.x < an.z) ? ivec3(0, 1, 2) : (an.y < an.z) ? ivec3(1, 2, 0) : ivec3(2, 0, 1);
        ivec3 me = ivec3(3) - mi - ma;
        vec2 uvA = vec2(p[ma.y], p[ma.z]), uvB = vec2(p[me.y], p[me.z]);
        vec2 dxA = vec2(dx[ma.y], dx[ma.z]), dyA = vec2(dy[ma.y], dy[ma.z]), dxB = vec2(dx[me.y], dx[me.z]), dyB = vec2(dy[me.y], dy[me.z]);
        vec2 w = vec2(an[ma.x], an[me.x]); w = clamp((w - 0.5773) / (1.0 - 0.5773), 0.0, 1.0); w = pow(w, vec2(2.0)); w /= (w.x + w.y + 1e-4);
        vec3 aA = textureGrad(uRAlb, vec3(uvA, layer), dxA, dyA).rgb, aB = textureGrad(uRAlb, vec3(uvB, layer), dxB, dyB).rgb;
        vec4 oA = textureGrad(uROrm, vec3(uvA, layer), dxA, dyA), oB = textureGrad(uROrm, vec3(uvB, layer), dxB, dyB);
        vec2 nA = textureGrad(uRNor, vec3(uvA, layer), dxA, dyA).xy * 2.0 - 1.0, nB = textureGrad(uRNor, vec3(uvB, layer), dxB, dyB).xy * 2.0 - 1.0;
        // whiteout blend of each projection's tangent-space normal into world space (sign of N picks the side)
        vec3 sN = sign(N + 1e-5);
        vec3 tA = vec3(nA * 1.0 + vec2(N[ma.y], N[ma.z]), abs(N[ma.x])), tB = vec3(nB * 1.0 + vec2(N[me.y], N[me.z]), abs(N[me.x]));
        vec3 wA = vec3(0.0), wB = vec3(0.0); wA[ma.y] = tA.x; wA[ma.z] = tA.y; wA[ma.x] = tA.z * sN[ma.x]; wB[me.y] = tB.x; wB[me.z] = tB.y; wB[me.x] = tB.z * sN[me.x];
        rockAlb = aA * w.x + aB * w.y; rockOrm = oA * w.x + oB * w.y; rockNrm = normalize(wA * w.x + wB * w.y);
        return vec4(rockAlb, 1.0);
      }
`;

/**
 * @param size        world size in metres (square, centred on the origin)
 * @param segments    grid resolution
 * @param heightAt    (x, z) => y
 * @param weightsAt   (x, z, out:Float32Array(7)) => void   biome weights (should sum to ~1)
 * @param arrays      {albedo, normal, orm} from assets.loadBiomeArrays
 * @param tileSizes   metres per texture repeat, one per biome layer (length <= 7)
 * @param rock        {layer, tile, start, full}: triplanar rock layer index, metres per repeat, slope (rise/run) where it starts / fully replaces the surface
 * @param rocks       {arrays: {albedo, normal, orm}, layers: [6], tiles: [6]} or null: the six cliff / mountain materials (strata, granite, scree, clay, moss, basalt) as texture
 *                    array layers (orm.b = HEIGHT, used to blend them); null = the single `rock` layer of `arrays` stands in for all six
 * @param rockAlt     [from, to]: altitude (m) where granite and basalt take over from the sedimentary cliffs
 * @param sites       [{x, z, hx, hy, yaw}]: building footprints; the ground gets contact shading around them (up to 6)
 * @param lake        {x, z, radius, level} or null: ground below level + ~0.5 m within `radius` of (x, z) is wet
 * @param walk        {easy, rough, max}: slope thresholds of the walkability overlay
 * @param field       {data: Uint8Array RGBA, res} or null: the tall-grass field as a colour map (rgb = tip colour as display values, a = coverage). Where the blades are far
 *                    or thinned out, the ground wears the field's colours, so the grass never ends at an edge. Seasons come from `fieldUniforms` (the grass uniforms:
 *                    uSeasonTint / uSeasonSat / uSeasonKeep / uFrost / uRipe), shared by reference, so they follow the grass with no per-frame copying.
 */
export function createTerrain({ size, segments, heightAt, weightsAt, arrays, tileSizes, splatRes = 512, normalStrength = 1.0, snowLine = 80,
  rock = { layer: 3, tile: 4.4, start: 0.46, full: 0.7 }, rocks = null, rockAlt = [40, 95], sites = [], lake = null, walk = { easy: 0.32, rough: 0.5, max: 0.68 }, field = null, fieldUniforms = null }) {
  const geo = new THREE.PlaneGeometry(size, size, segments, segments);
  geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, heightAt(pos.getX(i), pos.getZ(i)));
  geo.computeVertexNormals();

  // splat maps (7 weights in two RGBA8 textures)
  const s0 = new Uint8Array(splatRes * splatRes * 4), s1 = new Uint8Array(splatRes * splatRes * 4);
  const w = new Float32Array(7);
  for (let j = 0; j < splatRes; j++) {
    for (let i = 0; i < splatRes; i++) {
      const x = (i / (splatRes - 1) - 0.5) * size, z = (j / (splatRes - 1) - 0.5) * size;
      w.fill(0);
      weightsAt(x, z, w);
      let sum = 0; for (let k = 0; k < 7; k++) sum += w[k];
      const inv = sum > 1e-6 ? 1 / sum : 0, o = (j * splatRes + i) * 4;
      for (let k = 0; k < 4; k++) s0[o + k] = Math.round(w[k] * inv * 255);
      for (let k = 0; k < 3; k++) s1[o + k] = Math.round(w[4 + k] * inv * 255);
      s1[o + 3] = 255;
    }
  }
  const mkSplat = d => { const t = new THREE.DataTexture(d, splatRes, splatRes, THREE.RGBAFormat); t.magFilter = t.minFilter = THREE.LinearFilter; t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.needsUpdate = true; return t; };
  const splat0 = mkSplat(s0), splat1 = mkSplat(s1);

  let fieldTex = null;
  if (field) { fieldTex = new THREE.DataTexture(field.data, field.res, field.res, THREE.RGBAFormat); fieldTex.magFilter = fieldTex.minFilter = THREE.LinearFilter; fieldTex.wrapS = fieldTex.wrapT = THREE.ClampToEdgeWrapping; fieldTex.needsUpdate = true; }
  const neutral = { uSeasonTint: { value: new THREE.Vector3(1, 1, 1) }, uSeasonSat: { value: 1 }, uSeasonKeep: { value: 1 }, uFrost: { value: 0 }, uRipe: { value: 1 } };
  const fu = fieldUniforms ?? neutral;
  const R = rocks ?? { arrays, layers: Array(6).fill(rock.layer), tiles: Array(6).fill(rock.tile) };
  const L4 = (a, i) => new THREE.Vector4(a[i], a[i + 1], a[i + 2], a[i + 3]);
  const siteA = Array.from({ length: 6 }, (_, i) => { const S = sites[i]; return new THREE.Vector4(S?.x ?? 0, S?.z ?? 0, S?.hx ?? 0, S?.hy ?? 0); });
  const siteB = Array.from({ length: 6 }, (_, i) => { const S = sites[i]; return new THREE.Vector4(Math.cos(S?.yaw ?? 0), Math.sin(S?.yaw ?? 0), S?.ao ?? 2.6, 0); });
  const tiles = new Float32Array(8);
  tileSizes.forEach((t, i) => { tiles[i] = t; });
  const uniforms = {
    uAlb: { value: arrays.albedo }, uNor: { value: arrays.normal }, uOrm: { value: arrays.orm },
    uSplat0: { value: splat0 }, uSplat1: { value: splat1 }, uSize: { value: size }, uTile: { value: tiles },
    uNStr: { value: normalStrength }, uSnowLine: { value: snowLine },
    uRock: { value: new THREE.Vector4(rock.layer, rock.tile, rock.start, rock.full) },
    uRAlb: { value: R.arrays.albedo }, uRNor: { value: R.arrays.normal }, uROrm: { value: R.arrays.orm },
    uRLayer: { value: [L4(R.layers, 0), L4([...R.layers, 0, 0], 4)] }, uRTile: { value: [L4(R.tiles, 0), L4([...R.tiles, 1, 1], 4)] }, uRockAlt: { value: new THREE.Vector2(rockAlt[0], rockAlt[1]) },
    uSiteA: { value: siteA }, uSiteB: { value: siteB }, uSiteN: { value: Math.min(6, sites.length) },
    uLake: { value: new THREE.Vector4(lake?.x ?? 0, lake?.z ?? 0, lake?.radius ?? 0, lake?.level ?? -1e5) },
    uTerrainTime: { value: 0 },
    uWalk: { value: new THREE.Vector3(walk.easy, walk.rough, walk.max) }, uOverlay: { value: 0 },
    uGroundTint: { value: new THREE.Vector3(1, 1, 1) }, uSnow: { value: 0 },
    tField: { value: fieldTex }, uFieldOn: { value: field ? 1 : 0 },
    uSeasonTint: fu.uSeasonTint, uSeasonSat: fu.uSeasonSat, uSeasonKeep: fu.uSeasonKeep, uFrost: fu.uFrost, uRipe: fu.uRipe,
    uGrassField: { value: new THREE.Vector4(0, 0, 1, 0) },            // x, z, radius, fade of the tall-grass field around the view focus: the soil under it is shaded
  };
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1.0, metalness: 0.0 });
  mat.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = 'varying vec3 vWPos; varying vec3 vWNorm;\n' + shader.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\n vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz; vWNorm = normalize(mat3(modelMatrix) * normal);');
    shader.fragmentShader = `
      varying vec3 vWPos; varying vec3 vWNorm;
      uniform float uSnowLine, uTerrainTime, uOverlay, uSnow, uFieldOn, uSeasonSat, uSeasonKeep, uFrost, uRipe; uniform vec4 uRock, uLake, uGrassField; uniform vec3 uWalk, uGroundTint, uSeasonTint; uniform sampler2D tField; uniform vec4 uSiteA[6], uSiteB[6]; uniform int uSiteN;
      precision highp sampler2DArray;
      uniform sampler2DArray uAlb, uNor, uOrm; uniform sampler2D uSplat0, uSplat1;
      uniform float uSize; uniform float uTile[8]; uniform float uNStr;

      ${ROCK_SAMPLE_GLSL}
      float th21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float tvn(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
        return mix(mix(th21(i),th21(i+vec2(1,0)),f.x), mix(th21(i+vec2(0,1)),th21(i+vec2(1,1)),f.x), f.y); }
    ` + shader.fragmentShader
      .replace('#include <map_fragment>', `
        vec2 sUV = vWPos.xz / uSize + 0.5;
        vec4 sp0 = texture2D(uSplat0, sUV), sp1 = texture2D(uSplat1, sUV);
        float W[7]; W[0]=sp0.r; W[1]=sp0.g; W[2]=sp0.b; W[3]=sp0.a; W[4]=sp1.r; W[5]=sp1.g; W[6]=sp1.b;
        vec3 bAlb = vec3(0.); vec2 bNrm = vec2(0.); vec3 bOrm = vec3(0.); float wsum = 0.;
        float macro = smoothstep(0.30, 0.70, tvn(vWPos.xz * 0.045));
        mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
        vec2 gdx = dFdx(vWPos.xz), gdy = dFdy(vWPos.xz);                           // gradients taken in uniform control flow: the layer loop skips layers, so plain texture() would get undefined derivatives
        for (int i = 0; i < 7; i++) {
          float wi = W[i]; if (wi < 0.012) continue;
          vec2 uv = vWPos.xz / uTile[i];
          vec2 uv2 = rot * uv * 0.37 + 0.31, gx = gdx / uTile[i], gy = gdy / uTile[i], gx2 = rot * gx * 0.37, gy2 = rot * gy * 0.37;
          vec3 a1 = textureGrad(uAlb, vec3(uv, float(i)), gx, gy).rgb, a2 = textureGrad(uAlb, vec3(uv2, float(i)), gx2, gy2).rgb;
          bAlb += wi * mix(a1, a2, 0.45 * macro);
          bNrm += wi * (textureGrad(uNor, vec3(uv, float(i)), gx, gy).xy * 2.0 - 1.0);
          bOrm += wi * textureGrad(uOrm, vec3(uv, float(i)), gx, gy).rgb;
          wsum += wi;
        }
        wsum = max(wsum, 1e-3); bAlb /= wsum; bNrm /= wsum; bOrm /= wsum;
        // distant hills: autumn canopy patches (maple red, ginkgo gold, evergreen) fade in with distance over the forest floor
        {
          float rr = length(vWPos.xz);
          float farF = smoothstep(95.0, 250.0, rr);
          float cn = tvn(vWPos.xz * 0.016 + 3.0), cn2 = tvn(vWPos.xz * 0.06 + 17.0), cn3 = tvn(vWPos.xz * 0.21);
          vec3 canopy = mix(vec3(0.74, 0.20, 0.05), vec3(0.88, 0.62, 0.10), smoothstep(0.35, 0.7, cn));
          canopy = mix(canopy, vec3(0.20, 0.36, 0.10), smoothstep(0.52, 0.74, cn2));
          canopy = canopy * canopy * (0.55 + 0.5 * cn3);                       // display -> linear, with leaf-scale mottling
          float forestish = clamp(W[2] * 1.15 + W[0] * 0.35 + W[1] * 0.3, 0.0, 0.9);
          bAlb = mix(bAlb, canopy, farF * forestish);
          // snow dusting on high ground that is not too steep
          float snow = smoothstep(uSnowLine - 8.0, uSnowLine + 14.0, vWPos.y + 9.0 * tvn(vWPos.xz * 0.05)) * smoothstep(0.55, 0.9, normalize(vWNorm).y);
          bAlb = mix(bAlb, vec3(0.74, 0.78, 0.88), snow);
          bOrm.g = mix(bOrm.g, 0.55, snow);
        }
        // ---- rock: slope, altitude and noise choose between six materials (sedimentary strata, granite, scree, red clay, mossy rock, basalt); the two strongest are blended by
        //      their HEIGHT maps and projected biplanarly, so no face is ever a stretched planar texture. Relief comes from the normal maps of the same projections.
        vec3 nW = normalize(vWNorm); float ny = clamp(nW.y, 0.04, 1.0);
        float slope = sqrt(max(1.0 - ny * ny, 0.0)) / ny;
        float rockCover = smoothstep(uRock.z - 0.10, uRock.w - 0.02, slope);
        vec3 rockWN = nW;
        vec3 rdx = dFdx(vWPos), rdy = dFdy(vWPos);                                  // derivatives taken before any branch
        if (rockCover > 0.004) {
          vec2 wxz = vWPos.xz;
          float m1 = tvn(wxz * 0.021 + 3.7), m2 = tvn(wxz * 0.047 + 11.3), m3 = tvn(wxz * 0.11 + 5.1);
          float alt = vWPos.y + (m1 - 0.5) * 16.0;
          float high = smoothstep(uRockAlt.x, uRockAlt.y, alt);                       // the mountains: bare granite and basalt
          float steep = smoothstep(0.46, 1.0, slope);
          float ws[6];
          ws[0] = steep * (1.0 - high) * (0.55 + 0.45 * m2);                            // strata: the main cliff face
          ws[1] = steep * high * (0.7 + 0.3 * m1) + steep * 0.12;                       // granite
          ws[2] = smoothstep(0.34, 0.5, slope) * (1.0 - smoothstep(0.85, 1.2, slope)) * (0.45 + 0.55 * m1);   // scree: talus on moderate-to-steep slopes
          ws[3] = smoothstep(0.22, 0.38, slope) * (1.0 - smoothstep(0.52, 0.78, slope)) * smoothstep(0.42, 0.7, m2) * (1.0 - high);     // eroded red clay hillsides
          ws[4] = (1.0 - high) * smoothstep(0.55, 0.92, ny) * smoothstep(0.38, 0.68, m3) * (1.0 - steep * 0.6) * 0.9;                // moss on the flatter rock
          ws[5] = steep * smoothstep(0.64, 0.82, m3) * (0.35 + 0.65 * high);             // basalt outcrops
          int i1 = 0, i2 = 1; if (ws[1] > ws[0]) { i1 = 1; i2 = 0; }
          for (int i = 2; i < 6; i++) { if (ws[i] > ws[i1]) { i2 = i1; i1 = i; } else if (ws[i] > ws[i2]) { i2 = i; } }
          float w1 = max(ws[i1], 1e-3), w2 = ws[i2] > 0.04 ? ws[i2] : 0.0;
          // sample the two materials (biplanar albedo / ORM (b = height) / whiteout normals)
          vec4 r1 = rockSample(i1, vWPos, nW, rdx, rdy), r2 = vec4(0.0), o1, o2 = vec4(0.0); vec3 n1, n2 = nW; vec3 a1, a2 = vec3(0.0);
          a1 = rockAlb; o1 = rockOrm; n1 = rockNrm;
          float bl = 0.0;
          if (w2 > 0.0) {
            r2 = rockSample(i2, vWPos, nW, rdx, rdy); a2 = rockAlb; o2 = rockOrm; n2 = rockNrm;
            float tb = w2 / (w1 + w2);
            bl = smoothstep(0.42, 0.58, tb + (o2.b - o1.b) * 0.45 * min(1.0, tb * 4.0));
          }
          vec3 rAlb = mix(a1, a2, bl), rN = normalize(mix(n1, n2, bl)); vec4 rOrm = mix(o1, o2, bl);
          // large-scale life: warm / cool bedding bands that run on across tiles, vertical weathering streaks, blotchy staining
          float band = sin(vWPos.y * 1.35 + m2 * 5.0) * 0.5 + 0.5, streak = tvn(vec2(dot(wxz, vec2(1.7, 1.2)), vWPos.y * 0.13));
          rAlb *= mix(0.86, 1.10, band * ws[0]) * (1.0 - 0.28 * smoothstep(0.55, 0.92, streak) * steep) * (0.84 + 0.32 * m2);
          rAlb *= mix(vec3(1.0), vec3(1.10, 0.97, 0.84), band * 0.45 * ws[0]);
          bAlb = mix(bAlb, rAlb, rockCover); bOrm = mix(bOrm, rOrm.rgb, rockCover); bNrm *= (1.0 - rockCover);
          rockWN = normalize(mix(nW, rN, rockCover));
        }
        // ---- the shoreline is wet: darker, glossier ground within ~0.5 m above the waterline (the line breathes with the waves)
        float wetAmt = 0.0;
        if (uLake.z > 0.0) {
          float near = 1.0 - smoothstep(uLake.z * 0.8, uLake.z, length(vWPos.xz - uLake.xy));
          float swash = 0.05 * sin(uTerrainTime * 0.9 + vWPos.x * 0.35 + vWPos.z * 0.27) + 0.03 * sin(uTerrainTime * 1.7 + vWPos.z * 0.6);
          wetAmt = near * (1.0 - smoothstep(uLake.w - 0.02 + swash, uLake.w + 0.62 + swash, vWPos.y));
        }
        bAlb *= mix(1.0, 0.52, wetAmt); bOrm.g *= mix(1.0, 0.32, wetAmt);
        // ---- seasons: tint the grassy biomes, then lay snow on whatever faces up
        float grassy = clamp(W[0] + W[1] * 0.85 + W[5] * 0.6 + W[2] * 0.4, 0.0, 1.0);
        bAlb *= mix(vec3(1.0), uGroundTint, grassy);
        float gcov = (1.0 - smoothstep(uGrassField.z * 0.55, uGrassField.z, length(vWPos.xz - uGrassField.xy))) * uGrassField.w;      // how much of the ground the blades still cover (same fall-off as the grass shader)
        bAlb *= mix(1.0, 0.4, grassy * gcov);                                              // the soil under a tall canopy is deep in shade
        // ---- the field seen from afar: wherever the blades thin out, the ground wears the field's own colour and a hint of its texture, so nothing ends at an edge
        if (uFieldOn > 0.5) {
          vec4 fld = texture2D(tField, sUV);
          float fCov = fld.a * clamp(1.0 - W[4] - W[6] - W[3] * 0.8, 0.0, 1.0);          // not on roads, yards, gravel or bare rock (the splat knows them to the metre)
          if (fCov > 0.01) {
            vec3 gtc = fld.rgb * fld.rgb * uSeasonTint;                                  // tip colours are authored as display values; the season multiplies them
            vec3 fc = mix(vec3(dot(gtc, vec3(0.2126, 0.7152, 0.0722))), gtc, uSeasonSat);
            fc *= mix(vec3(1.0), vec3(1.18, 1.06, 0.72), 0.30 + 0.30 * uRipe);           // golden tips seen from above
            fc = mix(vec3(0.20, 0.14, 0.07) * 0.9, fc, clamp(uSeasonKeep * 1.25, 0.0, 1.0)); // die-back: bare stubble
            fc = mix(fc, vec3(0.62, 0.68, 0.76), uFrost * 0.45);
            // fine structure: wind-combed streaks and seed-head speckle, band-limited by the pixel footprint so it never aliases
            vec2 wp = vWPos.xz; float pf = max(length(gdx), length(gdy));
            float streak = tvn(vec2(dot(wp, vec2(0.94, 0.34)) * 1.7, dot(wp, vec2(-0.34, 0.94)) * 0.42)) * 0.6 + tvn(vec2(dot(wp, vec2(0.94, 0.34)) * 4.6, dot(wp, vec2(-0.34, 0.94)) * 1.1)) * 0.4;
            float fine = 1.0 - smoothstep(0.10, 0.55, pf * 4.6), speck = step(0.90, th21(floor(wp * 3.4))) * (1.0 - smoothstep(0.14, 0.5, pf * 3.4));
            float mid = tvn(wp * 0.55 + 7.0) * 0.55 + tvn(wp * 1.35 + 31.0) * 0.45, midFade = 1.0 - smoothstep(0.25, 1.3, pf * 1.35);   // plots of ripening grass, wind lanes: still readable from the far zoom
            fc *= 1.0 + (streak - 0.5) * 0.55 * fine + speck * 0.35 + (mid - 0.5) * 0.55 * midFade;
            float lumTex = clamp(dot(bAlb, vec3(0.2126, 0.7152, 0.0722)) * 3.2, 0.5, 1.5);   // keep a little of the ground texture
            vec3 fieldGround = fc * mix(1.0, lumTex, 0.35) * mix(1.0, 0.52, gcov);       // under dense blades the ground is in their shade
            bAlb = mix(bAlb, fieldGround, fCov * 0.92);
          }
        }
        float snowCover = uSnow * smoothstep(0.58, 0.9, ny) * (1.0 - wetAmt) * (0.78 + 0.22 * tvn(vWPos.xz * 0.35));
        bAlb = mix(bAlb, vec3(0.8, 0.84, 0.92), snowCover); bOrm.g = mix(bOrm.g, 0.6, snowCover);
        // ---- contact shading: ground meeting a building is darker (occluded by the walls and the eaves), fading over a couple of metres
        float contact = 0.0;
        for (int si = 0; si < 6; si++) {
          if (si >= uSiteN) break;
          vec4 sa = uSiteA[si], sb = uSiteB[si]; vec2 sd = vWPos.xz - sa.xy;
          vec2 ql = abs(vec2(sd.x * sb.x - sd.y * sb.y, -(sd.x * sb.y + sd.y * sb.x))) - sa.zw;
          float sdf = length(max(ql, 0.0)) + min(max(ql.x, ql.y), 0.0);
          contact = max(contact, 1.0 - smoothstep(0.0, sb.z, sdf));
        }
        contact = contact * contact * (3.0 - 2.0 * contact);
        bAlb *= 1.0 - 0.20 * contact; bOrm.r *= 1.0 - 0.32 * contact;
        diffuseColor.rgb *= bAlb;
        // ---- walkability overlay: what units can climb, what slows them, what is a cliff
        if (uOverlay > 0.5) {
          vec3 oc = slope <= uWalk.x ? vec3(0.15, 0.7, 0.2) : slope <= uWalk.y ? vec3(0.85, 0.8, 0.2) : slope <= uWalk.z ? vec3(0.95, 0.5, 0.1) : vec3(0.85, 0.1, 0.08);
          diffuseColor.rgb = mix(diffuseColor.rgb, oc * 0.7, 0.55);
        }
      `)
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = roughness * clamp(bOrm.g, 0.2, 1.0);')
      .replace('#include <normal_fragment_maps>', `
        {
          vec3 mapN = vec3(bNrm * uNStr, 0.0); mapN.z = sqrt(max(1.0 - dot(mapN.xy, mapN.xy), 0.0));
          vec2 uvA = vWPos.xz * 0.25;
          vec3 q0 = dFdx(-vViewPosition), q1 = dFdy(-vViewPosition);
          vec2 st0 = dFdx(uvA), st1 = dFdy(uvA);
          vec3 N = normal; vec3 q1p = cross(q1, N), q0p = cross(N, q0);
          vec3 T = q1p * st0.x + q0p * st1.x; vec3 B = q1p * st0.y + q0p * st1.y;
          float det = max(dot(T, T), dot(B, B)); float sc = det == 0.0 ? 0.0 : inversesqrt(det);
          normal = normalize(T * (mapN.x * sc) + B * (mapN.y * sc) + N * mapN.z);
          normal = normalize(mix(normal, normalize((viewMatrix * vec4(rockWN, 0.0)).xyz), rockCover));       // cliffs: the relief of the rock's own biplanar normal maps
        }`)
      .replace('#include <aomap_fragment>', 'reflectedLight.indirectDiffuse *= mix(1.0, bOrm.r, 0.9);');
  };
  const mesh = new THREE.Mesh(geo, mat);
  mesh.receiveShadow = true;
  mesh.name = 'terrain';
  return { mesh, heightAt, weightsAt, uniforms };
}
