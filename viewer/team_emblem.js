// Reference implementation of the character asset's runtime contract for TEAM COLOUR and FACTION EMBLEM (docs/character.md).
//   * `<asset>.team.png`   R = 1 where the engine may tint (lacing bands, cords, sash, the whole banner cloth). Same UVs as the albedo, flipY = false, NoColorSpace.
//   * `<asset>.emblems.png` + `.json`: a signed-distance sheet of faction crests. The albedo carries NO emblem; the engine draws one over the banner cloth, found by the
//     BIND-POSE position (`position` attribute, glTF axes) lying in the json's `banner.gltf` box. The same code works on every LOD (the cloth is two triangles from LOD1).
// One material per team (the emblem cell and the tint are uniforms of that material); the shader program is shared.
import * as THREE from 'three';

export async function loadTeamAssets(base, ver = '') {          // ver: a query suffix ('?v=<manifest.build>') so the side files are of the same build as the GLB
  const tex = (url, srgb) => new THREE.TextureLoader().loadAsync(url).then(t => { t.flipY = false; t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace; t.anisotropy = 4; return t; });
  const [mask, emblemTex, emblemMeta] = await Promise.all([
    tex(`${base}.team.png${ver}`, false),
    tex(`${base}.emblems.png${ver}`, false).catch(() => null),
    fetch(`${base}.emblems.json${ver}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  return { mask, emblemTex, emblemMeta };
}

/** cell rectangle (u0, v0, du, dv) of emblem `index` in the sheet */
export const emblemCell = (index, meta) => [(index % meta.cols) / meta.cols, Math.floor(index / meta.cols) / meta.rows, 1 / meta.cols, 1 / meta.rows];

/** @returns a team copy of `base` (the asset's material): lacing / sash / banner tinted to `tint` by the mask, the faction's emblem on the banner */
export function teamMaterial(base, { mask, tint, emblemTex = null, emblemMeta = null, emblem = 0 }) {
  const m = base.clone();
  const uTint = { value: new THREE.Color().copy(tint) };
  const hasMon = !!(emblemTex && emblemMeta);
  const cell = hasMon ? emblemCell(emblem, emblemMeta) : [0, 0, 1, 1];
  const rg = hasMon ? emblemMeta.banner.gltf : null;
  const ink = hasMon ? new THREE.Color().setRGB(...emblemMeta.ink_srgb, THREE.SRGBColorSpace).multiplyScalar(0.8) : new THREE.Color();
  m.onBeforeCompile = shader => {
    shader.uniforms.uTeamTint = uTint; shader.uniforms.tTeam = { value: mask };
    let vs = shader.vertexShader, fs = shader.fragmentShader;
    fs = fs.replace('#include <common>', '#include <common>\nuniform vec3 uTeamTint;\nuniform sampler2D tTeam;');
    let mon = '';
    if (hasMon) {
      shader.uniforms.tMon = { value: emblemTex };
      shader.uniforms.uMon = { value: new THREE.Vector4(...cell) };
      shader.uniforms.uBanA = { value: new THREE.Vector4(rg.x0, rg.w, rg.y_top, rg.h) };
      shader.uniforms.uBanB = { value: new THREE.Vector2(rg.z_min, rg.z_max) };
      shader.uniforms.uInk = { value: ink };
      vs = vs.replace('#include <common>', '#include <common>\nvarying vec3 vBind;\nvarying float vSide;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvBind = position; vSide = normal.z;');
      fs = fs.replace('#include <common>', '#include <common>\nvarying vec3 vBind;\nvarying float vSide;\nuniform sampler2D tMon;\nuniform vec4 uMon;\nuniform vec4 uBanA;\nuniform vec2 uBanB;\nuniform vec3 uInk;');
      mon = `
        { vec3 bp = vBind;                                                                   // bind pose: inside the banner box = the banner cloth
          if (bp.x > uBanA.x - 0.003 && bp.x < uBanA.x + uBanA.y + 0.003 && bp.y > uBanA.z - uBanA.w - 0.003 && bp.y < uBanA.z + 0.003 && bp.z > uBanB.x && bp.z < uBanB.y) {
            float u = (bp.x - uBanA.x) / uBanA.y, v = (uBanA.z - bp.y) / uBanA.w;
            if (vSide < 0.0) u = 1.0 - u;                                                    // the face seen from behind the unit: the cloth's +x is the viewer's left
            vec2 e = vec2((u - 0.5) / 0.86 + 0.5, (v - 0.40) * uBanA.w / (uBanA.y * 0.86) + 0.5);   // a square emblem across the cloth width, in the upper half
            if (e.x > 0.0 && e.x < 1.0 && e.y > 0.0 && e.y < 1.0) {
              float sd = texture2D(tMon, uMon.xy + uMon.zw * e).r;
              float w = max(fwidth(sd), 0.02);
              diffuseColor.rgb = mix(diffuseColor.rgb, uInk, smoothstep(0.5 - w, 0.5 + w, sd));
            } } }`;
    }
    fs = fs.replace('#include <map_fragment>', `#include <map_fragment>
        { float tm = smoothstep(0.35, 0.65, texture2D(tTeam, vMapUv).r);                    // threshold the filtered mask: no halo around the lacing
          float lum = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
          float far = smoothstep(4.0, 30.0, length(vViewPosition));                           // subtle up close, readable from the default zoom
          vec3 tinted = uTeamTint * clamp(lum * 5.0, 0.12, 0.85) * 0.75;
          diffuseColor.rgb = mix(diffuseColor.rgb, tinted, tm * mix(0.45, 1.0, far)); }${mon}`);
    shader.vertexShader = vs; shader.fragmentShader = fs;
  };
  m.customProgramCacheKey = () => (hasMon ? 'teamEmblem' : 'teamPlain');
  m.userData.uTint = uTint;
  return m;
}
