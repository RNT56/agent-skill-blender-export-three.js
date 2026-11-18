"""Inspect an exported GLB WITHOUT Blender (plain Python, stdlib only): verify the artefact, not the process.

    python3 gamepipe/gp_glb.py out/tree_autumn_01/tree_autumn_01_LOD0.glb
"""
import json
import struct
import sys


def read_json(path):
    with open(path, "rb") as fh:
        head = fh.read(20)
        if head[:4] != b"glTF":
            raise ValueError("not a GLB (bad magic)")
        n, kind = struct.unpack("<II", head[12:20])
        if kind != 0x4E4F534A:
            raise ValueError("first chunk is not JSON")
        return json.loads(fh.read(n))


def _read_chunks(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB (bad magic)")
    off, chunks = 12, []
    while off < len(data):
        n, kind = struct.unpack("<II", data[off:off + 8])
        chunks.append((kind, data[off + 8:off + 8 + n]))
        off += 8 + n
    return chunks


def _write_glb(path, jdict, bin_bytes):
    js = json.dumps(jdict, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bn = bytes(bin_bytes) + b"\0" * (-len(bin_bytes) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(bn), 0x004E4942) + bn)


def strip_fallback_images(path):
    """Blender's exporter can only ADD KTX2 next to the original PNG/JPEG (every texture ends up in the file twice).
    This removes the redundant fallback images of KHR_texture_basisu textures and compacts the BIN chunk.
    The result REQUIRES KHR_texture_basisu (three.js: KTX2Loader). Returns bytes saved."""
    chunks = _read_chunks(path)
    j = json.loads(chunks[0][1])
    binb = chunks[1][1] if len(chunks) > 1 else b""
    before = len(binb)
    tex, images = j.get("textures", []), j.get("images", [])
    fallback = set()
    for t in tex:
        e = t.get("extensions", {}).get("KHR_texture_basisu")
        if e and "source" in t:
            fallback.add(t["source"])
            del t["source"]
    in_use = set()
    for t in tex:
        if "source" in t:
            in_use.add(t["source"])
        for e in t.get("extensions", {}).values():
            if isinstance(e, dict) and "source" in e:
                in_use.add(e["source"])
    removed = {i for i in fallback if i not in in_use}
    if not removed:
        return 0
    keep = [i for i in range(len(images)) if i not in removed]
    remap_img = {old: new for new, old in enumerate(keep)}
    drop_bv = {images[i]["bufferView"] for i in removed if "bufferView" in images[i]}
    j["images"] = [images[i] for i in keep]
    for t in tex:
        if "source" in t:
            t["source"] = remap_img[t["source"]]
        for e in t.get("extensions", {}).values():
            if isinstance(e, dict) and "source" in e:
                e["source"] = remap_img[e["source"]]
    bvs = j["bufferViews"]
    keep_bv = [i for i in range(len(bvs)) if i not in drop_bv]
    remap_bv = {old: new for new, old in enumerate(keep_bv)}

    def data_ref(bv):                         # where this view's real bytes live in buffer 0
        ext = bv.get("extensions", {}).get("EXT_meshopt_compression")
        if ext is not None:
            return ext if ext.get("buffer", 0) == 0 else None
        return bv if bv.get("buffer", 0) == 0 else None

    new = bytearray()
    for i in sorted(keep_bv, key=lambda k: (data_ref(bvs[k]) or {"byteOffset": 0}).get("byteOffset", 0)):
        ref = data_ref(bvs[i])
        if ref is None:
            continue
        o, n = ref.get("byteOffset", 0), ref["byteLength"]
        new += b"\0" * (-len(new) % 4)
        ref["byteOffset"] = len(new)
        new += binb[o:o + n]
    j["bufferViews"] = [bvs[i] for i in keep_bv]
    for a in j.get("accessors", []):
        if "bufferView" in a:
            a["bufferView"] = remap_bv[a["bufferView"]]
    for im in j["images"]:
        if "bufferView" in im:
            im["bufferView"] = remap_bv[im["bufferView"]]
    j["buffers"][0]["byteLength"] = len(new)
    req = j.setdefault("extensionsRequired", [])
    if "KHR_texture_basisu" not in req:
        req.append("KHR_texture_basisu")
    _write_glb(path, j, new)
    return before - len(new)


def inspect(path):
    j = read_json(path)
    mats = []
    for m in j.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        mats.append({
            "name": m.get("name"), "alphaMode": m.get("alphaMode", "OPAQUE"), "doubleSided": bool(m.get("doubleSided")),
            "baseColorTexture": "baseColorTexture" in pbr,
            "metallicRoughnessTexture": "metallicRoughnessTexture" in pbr,
            "normalTexture": "normalTexture" in m, "occlusionTexture": "occlusionTexture" in m,
        })
    tris = 0
    for mesh in j.get("meshes", []):
        for p in mesh.get("primitives", []):
            if p.get("mode", 4) == 4 and "indices" in p:
                tris += j["accessors"][p["indices"]]["count"] // 3
    skins = j.get("skins", [])
    anims = []
    for a in j.get("animations", []):
        dur = 0.0
        for smp in a.get("samplers", []):
            mx = j["accessors"][smp["input"]].get("max")
            if mx:
                dur = max(dur, float(mx[0]))
        anims.append({"name": a.get("name"), "channels": len(a.get("channels", [])), "duration": round(dur, 4)})
    return {
        "skins": len(skins), "joints": max((len(sk.get("joints", [])) for sk in skins), default=0), "animations": anims,
        "meshes": len(j.get("meshes", [])), "triangles": tris, "materials": mats,
        "images": [{"name": i.get("name"), "mime": i.get("mimeType")} for i in j.get("images", [])],
        "textures": len(j.get("textures", [])),
        "extensionsUsed": j.get("extensionsUsed", []), "extensionsRequired": j.get("extensionsRequired", []),
    }


def check(path, expect=None):
    """Return a list of findings (dicts like the validator's) about the exported file itself."""
    out = []
    try:
        info = inspect(path)
    except Exception as exc:
        return [{"level": "error", "code": "GLB_UNREADABLE", "object": "-", "message": str(exc)}]
    if info["meshes"] == 0 or info["triangles"] == 0:
        out.append({"level": "error", "code": "GLB_EMPTY", "object": "-", "message": "exported file has no triangles"})
    for m in info["materials"]:
        if m["alphaMode"] == "BLEND":
            out.append({"level": "warn", "code": "GLB_ALPHA_BLEND", "object": m["name"],
                        "message": "alphaMode BLEND (sorting artefacts, no shadows); foliage should be MASK"})
        if not m["baseColorTexture"] and m["alphaMode"] == "MASK":
            out.append({"level": "error", "code": "GLB_MASK_NO_TEXTURE", "object": m["name"],
                        "message": "alpha-cut material has no base colour texture"})
    if expect and "animations" in expect:
        have = {a["name"] for a in info["animations"]}
        for n in expect["animations"]:
            if n not in have:
                out.append({"level": "error", "code": "GLB_ANIM_MISSING", "object": n, "message": "expected animation is not in the exported file"})
        if info["skins"] == 0:
            out.append({"level": "error", "code": "GLB_NO_SKIN", "object": "-", "message": "no skin exported"})
        if "joints_max" in expect and info["joints"] > expect["joints_max"]:
            out.append({"level": "error", "code": "GLB_JOINT_BUDGET", "object": "-",
                        "message": f"{info['joints']} joints exceeds {expect['joints_max']}"})
    if expect:
        for key, want in expect.get("alphaMode", {}).items():
            for m in info["materials"]:
                if key in (m["name"] or "") and m["alphaMode"] != want:
                    out.append({"level": "error", "code": "GLB_ALPHA_EXPECT", "object": m["name"],
                                "message": f"expected alphaMode {want}, got {m['alphaMode']}"})
        for key in expect.get("occlusion", []):
            for m in info["materials"]:
                if key in (m["name"] or "") and not m["occlusionTexture"]:
                    out.append({"level": "error", "code": "GLB_NO_OCCLUSION", "object": m["name"],
                                "message": "expected an occlusionTexture (ORM) but none was exported"})
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(inspect(p), indent=2))
        for f in check(p):
            print(f)
