"""Read-only GGUF metadata and tensor-table MTP inspector."""

from __future__ import annotations
import argparse
import json
import re
import struct
from pathlib import Path


class InvalidGGUF(ValueError):
    pass


class UnsupportedGGUF(ValueError):
    pass


class Reader:
    def __init__(self, f):
        self.f = f
        self.remaining = 64 * 1024 * 1024

    def read(self, n):
        if n < 0 or n > self.remaining:
            raise UnsupportedGGUF("GGUF tables exceed 64 MiB limit")
        self.remaining -= n
        b = self.f.read(n)
        if len(b) != n:
            raise InvalidGGUF("truncated GGUF")
        return b

    def num(self, fmt):
        return struct.unpack("<" + fmt, self.read(struct.calcsize(fmt)))[0]

    def string(self):
        n = self.num("Q")
        try:
            return self.read(n).decode("utf8")
        except UnicodeDecodeError as e:
            raise InvalidGGUF("invalid UTF-8") from e

    def value(self, t):
        fmts = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
        if t in fmts:
            return self.num(fmts[t])
        if t == 8:
            return self.string()
        if t == 9:
            sub, n = self.num("I"), self.num("Q")
            if sub == 9:
                raise UnsupportedGGUF("nested metadata arrays unsupported")
            if n > 1_000_000:
                raise UnsupportedGGUF("metadata array too large")
            return [self.value(sub) for _ in range(n)]
        raise UnsupportedGGUF(f"unsupported metadata type {t}")


# GGML block element counts and byte sizes for explicitly supported encodings.
GGML_SIZES = {0: (1, 4), 1: (1, 2), 2: (32, 18), 8: (32, 34), 12: (256, 144), 14: (256, 210)}
MAX_SIZE = (1 << 63) - 1


def payload_bytes(dims, kind):
    if kind not in GGML_SIZES:
        raise UnsupportedGGUF(f"unsupported tensor encoding {kind}")
    block, block_bytes = GGML_SIZES[kind]
    if not dims or any(type(n) is not int or n <= 0 for n in dims):
        raise InvalidGGUF("invalid tensor dimensions")
    if dims[0] % block:
        raise InvalidGGUF("tensor first dimension is not divisible by quantization block size")
    elements = 1
    for n in dims:
        if n > MAX_SIZE // elements:
            raise InvalidGGUF("tensor dimension overflow")
        elements *= n
    blocks = elements // block
    if blocks > MAX_SIZE // block_bytes:
        raise InvalidGGUF("tensor payload size overflow")
    return blocks * block_bytes


def validate_payloads(tensors, data_start, file_size, alignment):
    if type(alignment) is not int or alignment <= 0 or alignment & (alignment - 1):
        raise InvalidGGUF("invalid alignment")
    ranges = []
    ordered = []
    for name, (dims, kind, offset) in tensors.items():
        size = payload_bytes(dims, kind)
        if data_start > file_size or offset > file_size - data_start or size > file_size - data_start - offset:
            raise InvalidGGUF(f"tensor payload out of bounds: {name}")
        end = offset + size
        ranges.append((offset, end, name))
        ordered.append((offset, end, name))

    # Check ranges independently of descriptor order so aliasing is always
    # rejected, including aliases between trunk and MTP tensors.
    ranges.sort()
    furthest = None
    for current in ranges:
        if furthest is not None and current[0] < furthest[1]:
            raise InvalidGGUF(f"overlapping tensor payloads: {furthest[2]} and {current[2]}")
        if furthest is None or current[1] > furthest[1]:
            furthest = current

    for offset, _, name in ordered:
        if offset % alignment:
            raise InvalidGGUF(f"invalid tensor alignment: {name}")

    # The supported native layout places each tensor at the aligned end of
    # the previous descriptor's payload. Disjoint gaps or reordered ranges
    # are not known to be valid for this loader contract.
    expected = 0
    for offset, end, name in ordered:
        if offset != expected:
            raise UnsupportedGGUF(f"unsupported tensor payload ordering or gap before: {name}")
        expected = (end + alignment - 1) // alignment * alignment


def validate_mtp_shapes(metadata, tensors, index):
    emb = metadata.get("qwen35.embedding_length")
    if emb is not None and (type(emb) is not int or emb <= 0):
        raise InvalidGGUF("invalid embedding_length")
    if type(emb) is not int or emb <= 0:
        return False
    prefix = f"blk.{index}."
    shapes = {
        "nextn.eh_proj.weight": (2 * emb, emb),
        "nextn.enorm.weight": (emb,),
        "nextn.hnorm.weight": (emb,),
        "attn_norm.weight": (emb,),
        "post_attention_norm.weight": (emb,),
    }
    ff = metadata.get("qwen35.feed_forward_length")
    if type(ff) is int and ff > 0:
        shapes.update({"ffn_gate.weight": (emb, ff), "ffn_up.weight": (emb, ff), "ffn_down.weight": (ff, emb)})
    for suffix, expected in shapes.items():
        name = prefix + suffix
        if name in tensors and tensors[name][0] != expected:
            raise InvalidGGUF(f"invalid tensor shape: {name}")

    def layer_value(key):
        value = metadata.get(key)
        if isinstance(value, list):
            value = value[index] if index < len(value) else None
        if value is not None and (type(value) is not int or value <= 0):
            raise InvalidGGUF(f"invalid metadata: {key}")
        return value if type(value) is int and value > 0 else None

    heads = layer_value("qwen35.attention.head_count")
    kv_heads = layer_value("qwen35.attention.head_count_kv")
    key_dim = layer_value("qwen35.attention.key_length")
    value_dim = layer_value("qwen35.attention.value_length")
    if not all((heads, kv_heads, key_dim, value_dim)):
        return False
    if heads % kv_heads:
        raise InvalidGGUF("query head count is not divisible by KV head count")
    if key_dim != value_dim:
        raise InvalidGGUF("Qwen35 key and value head dimensions differ")
    q_width, k_width, v_width = 2 * heads * key_dim, kv_heads * key_dim, kv_heads * value_dim
    qkv_names = [prefix + f"attn_{part}.weight" for part in ("q", "k", "v")]
    fused_names = [prefix + "attn_qkv.weight"]
    separate = all(name in tensors for name in qkv_names)
    fused = [name for name in fused_names if name in tensors]
    if any(name in tensors for name in qkv_names) and fused:
        raise InvalidGGUF("both fused and separate QKV projections are present")
    if separate:
        expected = [(emb, q_width), (emb, k_width), (emb, v_width)]
        for name, shape in zip(qkv_names, expected):
            if tensors[name][0] != shape:
                raise InvalidGGUF(f"invalid tensor shape: {name}")
    elif fused:
        name = fused[0]
        if tensors[name][0] != (emb, q_width + k_width + v_width):
            raise InvalidGGUF(f"invalid tensor shape: {name}")
    else:
        raise InvalidGGUF("incomplete QKV projection group")
    for suffix, shape in {
        "attn_output.weight": (heads * key_dim, emb),
        "attn_q_norm.weight": (key_dim,),
        "attn_k_norm.weight": (key_dim,),
    }.items():
        name = prefix + suffix
        if name in tensors and tensors[name][0] != shape:
            raise InvalidGGUF(f"invalid tensor shape: {name}")
    return True


# Required suffixes; packed QKV can replace the three separate projections.
REQ = (
    "attn_norm.weight",
    "post_attention_norm.weight",
    "attn_q_norm.weight",
    "attn_k_norm.weight",
    "attn_output.weight",
    "ffn_gate.weight",
    "ffn_up.weight",
    "ffn_down.weight",
    "nextn.eh_proj.weight",
    "nextn.enorm.weight",
    "nextn.hnorm.weight",
)


def read_shard(path):
    size = path.stat().st_size
    with path.open("rb") as f:
        r = Reader(f)
        if r.read(4) != b"GGUF":
            raise InvalidGGUF("bad magic")
        ver = r.num("I")
        nt, nk = r.num("Q"), r.num("Q")
        if ver not in (2, 3):
            raise UnsupportedGGUF(f"GGUF version {ver} unsupported")
        if nt > 1_000_000 or nk > 1_000_000:
            raise UnsupportedGGUF("table count too large")
        metadata = {}
        for _ in range(nk):
            key = r.string()
            if key in metadata:
                raise InvalidGGUF("duplicate metadata key")
            metadata[key] = r.value(r.num("I"))
        tensors = {}
        for _ in range(nt):
            name = r.string()
            nd = r.num("I")
            if name in tensors:
                raise InvalidGGUF("duplicate tensor name")
            if not 1 <= nd <= 4:
                raise UnsupportedGGUF("unsupported tensor rank")
            dims = tuple(r.num("Q") for _ in range(nd))
            kind, offset = r.num("I"), r.num("Q")
            if not all(dims):
                raise InvalidGGUF("zero tensor dimension")
            tensors[name] = (dims, kind, offset)
        alignment = metadata.get("general.alignment", 32)
        if type(alignment) is not int or alignment <= 0 or alignment & (alignment - 1):
            raise InvalidGGUF("invalid alignment")
        data_start = (f.tell() + alignment - 1) // alignment * alignment
    validate_payloads(tensors, data_start, size, alignment)
    return metadata, tensors


def read_shards(path):
    metadata, tensors = read_shard(path)
    split_keys = ("split.no", "split.count", "split.tensors.count")
    if not any(k in metadata for k in split_keys):
        return metadata, tensors
    if not all(k in metadata for k in split_keys):
        raise InvalidGGUF("incomplete split metadata")
    no, count, total = (metadata[k] for k in split_keys)
    if (
        any(type(v) is not int for v in (no, count, total))
        or not 1 < count <= 10000
        or not 0 <= no < count
        or total < 0
    ):
        raise InvalidGGUF("invalid split metadata")
    if total > 1_000_000:
        raise UnsupportedGGUF("aggregate tensor count too large")
    match = re.fullmatch(r"(.*)-(\d{5})-of-(\d{5})\.gguf", path.name, re.IGNORECASE)
    if not match:
        raise UnsupportedGGUF("split shard filename does not follow GGUF convention")
    if int(match[2]) != no + 1 or int(match[3]) != count:
        raise InvalidGGUF("split shard filename conflicts with metadata")
    merged = dict(tensors)
    common = {k: v for k, v in metadata.items() if k not in split_keys}
    for index in range(count):
        if index == no:
            continue
        other = path.with_name(f"{match[1]}-{index + 1:05d}-of-{count:05d}.gguf")
        if not other.is_file():
            raise InvalidGGUF(f"missing split shard: {other.name}")
        shard_meta, shard_tensors = read_shard(other)
        split_values = tuple(shard_meta.get(k) for k in split_keys)
        if any(type(v) is not int for v in split_values) or split_values != (index, count, total):
            raise InvalidGGUF(f"conflicting split shard metadata: {other.name}")
        for key, value in shard_meta.items():
            if key in split_keys:
                continue
            if key in common and (type(common[key]) is not type(value) or common[key] != value):
                raise InvalidGGUF(f"conflicting split metadata: {key}")
            common[key] = value
        duplicates = merged.keys() & shard_tensors.keys()
        if duplicates:
            raise InvalidGGUF(f"duplicate tensor name across shards: {min(duplicates)}")
        merged.update(shard_tensors)
    if len(merged) != total:
        raise InvalidGGUF("split aggregate tensor count mismatch")
    return common, merged


def inspect_gguf(path: Path) -> dict:
    p = Path(path)
    out = {
        "schema": "local-mtp-capability-v1",
        "file": {"name": p.name, "size_bytes": None, "architecture": "unknown", "quantization": "unknown"},
        "mtp": {"status": "unknown", "nextn_predict_layers": None, "tensor_evidence": [], "reason": "Not inspected"},
        "runtime": {
            "backend": "unknown",
            "version": None,
            "mtp_control_available": None,
            "runtime_visibility": "unavailable_from_agent_environment",
            "active_backend_identity": "unknown",
            "runtime_mtp_compatibility": "unverified",
        },
    }
    try:
        size = p.stat().st_size
        out["file"]["size_bytes"] = size
        m, tensors = read_shards(p)
        arch = m.get("general.architecture")
        out["file"]["architecture"] = arch if isinstance(arch, str) else "unknown"
        out["file"]["quantization"] = m.get("general.file_type", "unknown")
        if arch != "qwen35":
            raise UnsupportedGGUF(f"architecture unsupported: {arch}")
        count = m.get("qwen35.nextn_predict_layers", 0)
        out["mtp"]["nextn_predict_layers"] = count
        out["mtp"]["tensor_evidence"] = sorted(n for n in tensors if ".nextn." in n)
        if type(count) is not int or count < 0:
            raise InvalidGGUF("invalid nextn_predict_layers")
        if count == 0:
            if out["mtp"]["tensor_evidence"]:
                raise InvalidGGUF("MTP tensors present but metadata declares zero layers")
            out["mtp"].update(status="absent", reason="MTP metadata and block tensors absent")
            return out
        if count != 1:
            raise UnsupportedGGUF("Qwen35 loader contract supports exactly one MTP block")
        blocks = m.get("qwen35.block_count")
        if blocks is None:
            raise UnsupportedGGUF("missing qwen35.block_count")
        if type(blocks) is not int or blocks <= count:
            raise InvalidGGUF("invalid qwen35.block_count")
        index = blocks - count
        if any(".nextn." in n and not n.startswith(f"blk.{index}.nextn.") for n in tensors):
            raise InvalidGGUF("NextN tensor outside declared MTP block")
        known_nextn = {
            f"blk.{index}.nextn.{suffix}.weight"
            for suffix in ("eh_proj", "enorm", "hnorm", "embed_tokens", "shared_head_head", "shared_head_norm")
        }
        if any(".nextn." in n and n not in known_nextn for n in tensors):
            raise UnsupportedGGUF("unsupported NextN tensor")
        out["mtp"]["tensor_evidence"] = sorted(n for n in tensors if ".nextn." in n or n.startswith(f"blk.{index}."))
        trunk = any(
            n.startswith("blk.") and n.split(".")[1].isdigit() and int(n.split(".")[1]) < index for n in tensors
        )
        if not out["mtp"]["tensor_evidence"]:
            if trunk:
                out["mtp"].update(status="absent", representation="trunk-only", reason="Appended MTP tensors absent")
                return out
            raise UnsupportedGGUF("no trunk or MTP block tensors found")
        out["mtp"]["representation"] = "bundled" if trunk else "mtp-only"
        missing = [f"blk.{index}.{suffix}" for suffix in REQ if f"blk.{index}.{suffix}" not in tensors]
        qkv = [f"blk.{index}.attn_qkv.weight"]
        if not all(f"blk.{index}.attn_{x}.weight" in tensors for x in ("q", "k", "v")) and not any(
            x in tensors for x in qkv
        ):
            missing.append("QKV packed or separate projections")
        if missing:
            raise InvalidGGUF("incomplete MTP block: " + ", ".join(missing))
        complete = validate_mtp_shapes(m, tensors, index)
        ff = m.get("qwen35.feed_forward_length")
        if ff is not None and (type(ff) is not int or ff <= 0):
            raise InvalidGGUF("invalid feed_forward_length")
        if not complete or ff is None:
            raise UnsupportedGGUF("missing metadata required for MTP shapes")
        emb = m["qwen35.embedding_length"]
        prefix = f"blk.{index}.nextn."
        candidates = (
            prefix + "embed_tokens.weight",
            prefix + "shared_head_head.weight",
            "token_embd.weight",
            "output.weight",
        )
        tokens = m.get("tokenizer.ggml.tokens")
        if tokens is not None and (not isinstance(tokens, list) or not tokens):
            raise InvalidGGUF("invalid tokenizer token list")
        vocab = len(tokens) if tokens is not None else None
        for name in candidates:
            if name in tensors:
                shape = tensors[name][0]
                if len(shape) != 2 or shape[0] != emb or (vocab is not None and shape[1] != vocab):
                    raise InvalidGGUF(f"invalid tensor shape: {name}")
                vocab = shape[1]
        for name in (prefix + "shared_head_norm.weight", "output_norm.weight"):
            if name in tensors and tensors[name][0] != (emb,):
                raise InvalidGGUF(f"invalid tensor shape: {name}")
        available = (
            prefix + "embed_tokens.weight" in tensors or "token_embd.weight" in tensors,
            prefix + "shared_head_head.weight" in tensors
            or "output.weight" in tensors
            or "token_embd.weight" in tensors,
            prefix + "shared_head_norm.weight" in tensors or "output_norm.weight" in tensors,
        )
        if not all(available):
            raise UnsupportedGGUF("MTP fallback tensors require a compatible separate component")
        out["mtp"].update(
            status="present",
            reason="MTP tensors, supported payload bounds, shapes and local fallbacks validated; runtime compatibility unverified",
        )
    except UnsupportedGGUF as e:
        out["mtp"]["reason"] = str(e)
    except (OSError, InvalidGGUF, struct.error) as e:
        out["mtp"].update(status="invalid", reason=str(e))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-i", "--input", "--input-file", dest="input_file", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(inspect_gguf(a.input_file), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
