// Heightfield terrain with N-biome PBR splatting: texture arrays (albedo / normal / ORM), splat maps from a weights callback,
// anti-tiling (second sample at a rotated/rescaled UV, blended by low-frequency noise), derivative-based tangent frame.
// Plus: triplanar rock on steep faces (cliffs are not stretched planar textures), shoreline wetness around a lake, a walkability overlay
// (green/yellow/orange/red by slope, thresholds supplied by the game), and seasonal ground tint + snow cover, all driven by live uniforms.
import * as THREE from 'three';

/**
 * @param size        world size in metres (square, centred on the origin)
 * @param segments    grid resolution
 * @param heightAt    (x, z) => y
 * @param weightsAt   (x, z, out:Float32Array(7)) => void   biome weights (should sum to ~1)
 * @param arrays      {albedo, normal, orm} from assets.loadBiomeArrays
 * @param tileSizes   metres per texture repeat, one per biome layer (length <= 7)
 * @param rock        {layer, tile, start, full}: triplanar rock layer index, metres per repeat, slope (rise/run) where it starts / fully replaces the surface
 * @param lake        {x, z, radius, level} or null: ground below level + ~0.5 m within `radius` of (x, z) is wet
 * @param walk        {easy, rough, max}: slope thresholds of the walkability overlay
 */
export function createTerrain({ size, segments, heightAt, weightsAt, arrays, tileSizes, splatRes = 512, normalStrength = 1.0, snowLine = 80,
  rock = { layer: 3, tile: 4.4, start: 0.46, full: 0.7 }, lake = null, walk = { easy: 0.32, rough: 0.5, max: 0.68 } }) {
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

  const tiles = new Float32Array(8);
  tileSizes.forEach((t, i) => { tiles[i] = t; });
  const uniforms = {
    uAlb: { value: arrays.albedo }, uNor: { value: arrays.normal }, uOrm: { value: arrays.orm },
    uSplat0: { value: splat0 }, uSplat1: { value: splat1 }, uSize: { value: size }, uTile: { value: tiles },
    uNStr: { value: normalStrength }, uSnowLine: { value: snowLine },
    uRock: { value: new THREE.Vector4(rock.layer, rock.tile, rock.start, rock.full) },
    uLake: { value: new THREE.Vector4(lake?.x ?? 0, lake?.z ?? 0, lake?.radius ?? 0, lake?.level ?? -1e5) },
    uTerrainTime: { value: 0 },
    uWalk: { value: new THREE.Vector3(walk.easy, walk.rough, walk.max) }, uOverlay: { value: 0 },
    uGroundTint: { value: new THREE.Vector3(1, 1, 1) }, uSnow: { value: 0 },
    uGrassField: { value: new THREE.Vector4(0, 0, 1, 0) },            // x, z, radius, fade of the tall-grass field around the view focus: the soil under it is shaded
  };
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1.0, metalness: 0.0 });
  mat.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = 'varying vec3 vWPos; varying vec3 vWNorm;\n' + shader.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\n vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz; vWNorm = normalize(mat3(modelMatrix) * normal);');
    shader.fragmentShader = `
      varying vec3 vWPos; varying vec3 vWNorm;
      uniform float uSnowLine, uTerrainTime, uOverlay, uSnow; uniform vec4 uRock, uLake, uGrassField; uniform vec3 uWalk, uGroundTint;
      precision highp sampler2DArray;
      uniform sampler2DArray uAlb, uNor, uOrm; uniform sampler2D uSplat0, uSplat1;
      uniform float uSize; uniform float uTile[8]; uniform float uNStr;
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
        // ---- steep faces: triplanar rock (the layer's albedo / ORM projected along all three axes, weighted by the normal)
        vec3 nW = normalize(vWNorm); float ny = clamp(nW.y, 0.04, 1.0);
        float slope = sqrt(max(1.0 - ny * ny, 0.0)) / ny;
        float cliff = smoothstep(uRock.z, uRock.w, slope);
        vec3 gdx3 = dFdx(vWPos) / uRock.y, gdy3 = dFdy(vWPos) / uRock.y;           // derivatives again taken before the branch
        if (cliff > 0.004) {
          vec3 bw = pow(abs(nW), vec3(4.0)); bw /= (bw.x + bw.y + bw.z);
          vec3 pr = vWPos / uRock.y; float rl = uRock.x;
          vec3 rAlb = textureGrad(uAlb, vec3(pr.zy, rl), gdx3.zy, gdy3.zy).rgb * bw.x + textureGrad(uAlb, vec3(pr.xz, rl), gdx3.xz, gdy3.xz).rgb * bw.y + textureGrad(uAlb, vec3(pr.xy, rl), gdx3.xy, gdy3.xy).rgb * bw.z;
          vec3 rOrm = textureGrad(uOrm, vec3(pr.zy, rl), gdx3.zy, gdy3.zy).rgb * bw.x + textureGrad(uOrm, vec3(pr.xz, rl), gdx3.xz, gdy3.xz).rgb * bw.y + textureGrad(uOrm, vec3(pr.xy, rl), gdx3.xy, gdy3.xy).rgb * bw.z;
          float strata = 0.86 + 0.14 * sin(vWPos.y * 2.7 + tvn(vWPos.xz * 0.11) * 4.0);          // faint horizontal bedding
          bAlb = mix(bAlb, rAlb * strata * 0.92, cliff); bOrm = mix(bOrm, rOrm, cliff); bNrm *= (1.0 - 0.8 * cliff);
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
        float gcov = (1.0 - smoothstep(uGrassField.z * 0.7, uGrassField.z, length(vWPos.xz - uGrassField.xy))) * uGrassField.w;
        bAlb *= mix(1.0, 0.4, grassy * gcov);                                              // the soil under a tall canopy is deep in shade
        float snowCover = uSnow * smoothstep(0.58, 0.9, ny) * (1.0 - wetAmt) * (0.78 + 0.22 * tvn(vWPos.xz * 0.35));
        bAlb = mix(bAlb, vec3(0.8, 0.84, 0.92), snowCover); bOrm.g = mix(bOrm.g, 0.6, snowCover);
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
        }`)
      .replace('#include <aomap_fragment>', 'reflectedLight.indirectDiffuse *= mix(1.0, bOrm.r, 0.9);');
  };
  const mesh = new THREE.Mesh(geo, mat);
  mesh.receiveShadow = true;
  mesh.name = 'terrain';
  return { mesh, heightAt, weightsAt, uniforms };
}
