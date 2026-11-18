// Asset loading: GLB with meshopt geometry + KTX2 (BasisU) textures, and biome PBR texture arrays.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

/** GLTF loader that understands everything the blend-up pipeline exports (EXT_meshopt_compression + KHR_texture_basisu). */
export function createLoader(renderer, { basisPath = 'https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/basis/' } = {}) {
  const ktx2 = new KTX2Loader().setTranscoderPath(basisPath).detectSupport(renderer);
  return new GLTFLoader().setKTX2Loader(ktx2).setMeshoptDecoder(MeshoptDecoder);
}

export async function loadGLB(loader, url) {
  return loader.loadAsync(url);
}

async function loadPixels(url, size) {
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob, { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0, size, size);
  const src = ctx.getImageData(0, 0, size, size).data;
  // rows reversed: image top must land at v=1 so tangent-space normal maps (green = +V = image up) match the GL convention
  const out = new Uint8Array(src.length);
  const row = size * 4;
  for (let y = 0; y < size; y++) out.set(src.subarray(y * row, (y + 1) * row), (size - 1 - y) * row);
  return out;
}

/**
 * Biome texture arrays: one layer per material, three arrays (albedo sRGB, normal, ORM).
 * Files: <base>/<name>_albedo.jpg, _normal.png, _orm.png  (the output of `bin/gp textures`).
 */
export async function loadBiomeArrays(base, names, renderer, size = 1024) {
  const layers = { albedo: [], normal: [], orm: [] };
  await Promise.all(names.map(async (n, i) => {
    layers.albedo[i] = await loadPixels(`${base}/${n}_albedo.jpg`, size);
    layers.normal[i] = await loadPixels(`${base}/${n}_normal.png`, size);
    layers.orm[i] = await loadPixels(`${base}/${n}_orm.png`, size);
  }));
  const make = (arr, srgb) => {
    const data = new Uint8Array(size * size * 4 * names.length);
    arr.forEach((a, i) => data.set(a, i * size * size * 4));
    const t = new THREE.DataArrayTexture(data, size, size, names.length);
    t.format = THREE.RGBAFormat;
    t.type = THREE.UnsignedByteType;
    t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.magFilter = THREE.LinearFilter;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.generateMipmaps = true;
    t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    t.needsUpdate = true;
    return t;
  };
  return { albedo: make(layers.albedo, true), normal: make(layers.normal, false), orm: make(layers.orm, false) };
}
