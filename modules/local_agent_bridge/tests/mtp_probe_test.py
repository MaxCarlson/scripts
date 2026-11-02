import struct
from pathlib import Path
import importlib.util
import pytest

spec = importlib.util.spec_from_file_location(
    "mtp_probe", Path(__file__).parents[1] / "local_agent_bridge" / "mtp_probe.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
inspect_gguf = module.inspect_gguf


def s(v):
    b = v.encode()
    return struct.pack("<Q", len(b)) + b


def fixture(path, metadata, tensors):
    data = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(metadata))
    for key, value in metadata.items():
        data += s(key)
        if isinstance(value, str):
            data += struct.pack("<I", 8) + s(value)
        else:
            data += struct.pack("<II", 4, value)
    for name in tensors:
        data += s(name) + struct.pack("<IQIQ", 1, 1, 0, 0)
    if tensors:
        data += b"\0" * (-len(data) % 32) + b"\0" * 4
    path.write_bytes(data)


def test_metadata_and_mtp_tensors(tmp_path):
    p = tmp_path / "model.gguf"
    fixture(p, {"general.architecture": "qwen3", "qwen3.block_count": 1, "qwen3.nextn_predict_layers": 1}, [])
    assert inspect_gguf(p)["mtp"]["status"] == "unknown"


def test_missing_file(tmp_path):
    assert inspect_gguf(tmp_path / "missing.gguf")["mtp"]["status"] == "invalid"


@pytest.mark.parametrize("kind,dims,expected", [(1, (8, 2), 32), (12, (256, 2), 288), (14, (256, 2), 420)])
def test_payload_size(kind, dims, expected):
    assert module.payload_bytes(dims, kind) == expected


@pytest.mark.parametrize("dims,kind", [((255, 2), 12), ((256, 0), 14), ((2**63, 2), 1)])
def test_invalid_dimensions(dims, kind):
    with pytest.raises(module.InvalidGGUF):
        module.payload_bytes(dims, kind)


def test_unsupported_type():
    with pytest.raises(module.UnsupportedGGUF):
        module.payload_bytes((256,), 999)


def test_payload_boundary():
    module.validate_payloads({"x": ((256,), 12, 0)}, 64, 208, 32)
    with pytest.raises(module.InvalidGGUF, match="bounds"):
        module.validate_payloads({"x": ((256,), 12, 0)}, 64, 207, 32)


def test_alignment():
    with pytest.raises(module.InvalidGGUF, match="alignment"):
        module.validate_payloads({"x": ((8,), 1, 1)}, 32, 128, 32)
    with pytest.raises(module.InvalidGGUF, match="alignment"):
        module.validate_payloads({}, 32, 128, 3)


@pytest.mark.parametrize("bad", [False, True])
def test_nextn_shapes(bad):
    tensors = {
        f"blk.64.nextn.{name}.weight": (dims, 1, 0)
        for name, dims in [("eh_proj", (16, 8)), ("enorm", (8,)), ("hnorm", (8,))]
    }
    if bad:
        tensors["blk.64.nextn.eh_proj.weight"] = ((8, 24), 1, 0)
    if bad:
        with pytest.raises(module.InvalidGGUF, match="shape"):
            module.validate_mtp_shapes({"qwen35.embedding_length": 8}, tensors, 64)
    else:
        assert module.validate_mtp_shapes({"qwen35.embedding_length": 8}, tensors, 64) is False


def complete_fixture(path, truncate=0, wrong_shape=False, block_count=65):
    names = [f"blk.64.{suffix}" for suffix in module.REQ] + [f"blk.64.attn_{x}.weight" for x in ("q", "k", "v")]
    metadata = {"general.architecture": "qwen35", "qwen35.nextn_predict_layers": 1, "qwen35.embedding_length": 256}
    if block_count is not None:
        metadata["qwen35.block_count"] = block_count
    data = b"GGUF" + struct.pack("<IQQ", 3, len(names), len(metadata))
    for key, value in metadata.items():
        data += s(key) + (struct.pack("<I", 8) + s(value) if isinstance(value, str) else struct.pack("<II", 4, value))
    offset = 0
    for name in names:
        dims = (256,)
        if name.endswith("eh_proj.weight"):
            dims = (512, 256) if not wrong_shape else (256, 512)
        size = module.payload_bytes(dims, 12)
        data += (
            s(name)
            + struct.pack("<I", len(dims))
            + b"".join(struct.pack("<Q", v) for v in dims)
            + struct.pack("<IQ", 12, offset)
        )
        offset = (offset + size + 31) // 32 * 32
    data += b"\0" * (-len(data) % 32)
    data += b"\0" * (offset - truncate)
    path.write_bytes(data)


def test_inspector_checks_payload_and_shape(tmp_path):
    p = tmp_path / "test.gguf"
    complete_fixture(p)
    assert inspect_gguf(p)["mtp"]["status"] == "unknown"
    complete_fixture(p, truncate=32)
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"
    complete_fixture(p, wrong_shape=True)
    assert "shape" in inspect_gguf(p)["mtp"]["reason"]


ATTN_META = {
    "qwen35.embedding_length": 8,
    "qwen35.attention.head_count": 2,
    "qwen35.attention.head_count_kv": 1,
    "qwen35.attention.key_length": 4,
    "qwen35.attention.value_length": 4,
}


def attention_tensors(fused=False):
    t = {}
    if fused:
        t["blk.64.attn_qkv.weight"] = ((8, 24), 1, 0)
    else:
        t.update(
            {
                "blk.64.attn_q.weight": ((8, 16), 1, 0),
                "blk.64.attn_k.weight": ((8, 4), 1, 0),
                "blk.64.attn_v.weight": ((8, 4), 1, 0),
            }
        )
    t.update(
        {
            "blk.64.attn_output.weight": ((8, 8), 1, 0),
            "blk.64.attn_q_norm.weight": ((4,), 1, 0),
            "blk.64.attn_k_norm.weight": ((4,), 1, 0),
        }
    )
    return t


@pytest.mark.parametrize("fused", [False, True])
def test_attention_projection_shapes(fused):
    assert module.validate_mtp_shapes(ATTN_META, attention_tensors(fused), 64)


@pytest.mark.parametrize(
    "name,shape",
    [
        ("attn_q.weight", (8, 7)),
        ("attn_k.weight", (8, 3)),
        ("attn_v.weight", (8, 3)),
        ("attn_output.weight", (7, 8)),
        ("attn_q_norm.weight", (8,)),
        ("attn_k_norm.weight", (8,)),
    ],
)
def test_invalid_attention_shapes(name, shape):
    t = attention_tensors()
    t["blk.64." + name] = (shape, 1, 0)
    with pytest.raises(module.InvalidGGUF, match="shape"):
        module.validate_mtp_shapes(ATTN_META, t, 64)


def test_missing_head_metadata_is_unknown():
    assert module.validate_mtp_shapes({"qwen35.embedding_length": 8}, attention_tensors(), 64) is False


def test_head_metadata_arrays():
    meta = {k: [v] * 65 for k, v in ATTN_META.items() if k.startswith("qwen35.attention.")}
    meta["qwen35.embedding_length"] = 8
    assert module.validate_mtp_shapes(meta, attention_tensors(), 64)


def test_trunk_only_does_not_treat_block_64_as_mtp(tmp_path):
    p = tmp_path / "trunk.gguf"
    fixture(p, {"general.architecture": "qwen35", "qwen35.block_count": 65}, [])
    assert inspect_gguf(p)["mtp"]["status"] == "absent"


def test_missing_block_count_is_unknown(tmp_path):
    p = tmp_path / "missing-block-count.gguf"
    complete_fixture(p, block_count=None)
    assert "block_count" in inspect_gguf(p)["mtp"]["reason"]


def test_missing_split_shard_is_invalid(tmp_path):
    p = tmp_path / "model-00001-of-00002.gguf"
    fixture(p, {"general.architecture": "qwen35", "split.no": 0, "split.count": 2, "split.tensors.count": 0}, [])
    result = inspect_gguf(p)
    assert result["mtp"]["status"] == "invalid"
    assert "shard" in result["mtp"]["reason"]


def test_complete_empty_split_is_absent(tmp_path):
    for index in range(2):
        fixture(
            tmp_path / f"model-{index + 1:05d}-of-00002.gguf",
            {"general.architecture": "qwen35", "split.no": index, "split.count": 2, "split.tensors.count": 0},
            [],
        )
    assert inspect_gguf(tmp_path / "model-00002-of-00002.gguf")["mtp"]["status"] == "absent"


def test_conflicting_split_metadata_is_invalid(tmp_path):
    for index in range(2):
        fixture(
            tmp_path / f"model-{index + 1:05d}-of-00002.gguf",
            {
                "general.architecture": "qwen35" if index == 0 else "qwen3",
                "split.no": index,
                "split.count": 2,
                "split.tensors.count": 0,
            },
            [],
        )
    result = inspect_gguf(tmp_path / "model-00001-of-00002.gguf")
    assert result["mtp"]["status"] == "invalid"
    assert "conflicting split metadata" in result["mtp"]["reason"]


def test_declared_mtp_without_appended_block_is_trunk_only(tmp_path):
    p = tmp_path / "trunk.gguf"
    fixture(
        p,
        {"general.architecture": "qwen35", "qwen35.block_count": 3, "qwen35.nextn_predict_layers": 1},
        ["blk.0.attn_norm.weight"],
    )
    result = inspect_gguf(p)
    assert result["mtp"]["status"] == "absent"
    assert result["mtp"]["representation"] == "trunk-only"


def shaped_fixture(path, tensors, extra=None):
    metadata = {
        "general.architecture": "qwen35",
        "qwen35.block_count": 3,
        "qwen35.nextn_predict_layers": 1,
        "qwen35.embedding_length": 8,
        "qwen35.feed_forward_length": 16,
        "qwen35.attention.head_count": 2,
        "qwen35.attention.head_count_kv": 1,
        "qwen35.attention.key_length": 4,
        "qwen35.attention.value_length": 4,
    }
    metadata.update(extra or {})
    data = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(metadata))
    for key, value in metadata.items():
        data += s(key) + (struct.pack("<I", 8) + s(value) if isinstance(value, str) else struct.pack("<II", 4, value))
    offset = 0
    for name, dims in tensors.items():
        data += s(name) + struct.pack("<I", len(dims))
        data += b"".join(struct.pack("<Q", dim) for dim in dims)
        data += struct.pack("<IQ", 1, offset)
        offset = (offset + module.payload_bytes(dims, 1) + 31) // 32 * 32
    data += b"\0" * (-len(data) % 32) + b"\0" * offset
    path.write_bytes(data)


def valid_mtp_tensors():
    shapes = {
        "attn_norm.weight": (8,),
        "post_attention_norm.weight": (8,),
        "attn_q_norm.weight": (4,),
        "attn_k_norm.weight": (4,),
        "attn_output.weight": (8, 8),
        "attn_q.weight": (8, 16),
        "attn_k.weight": (8, 4),
        "attn_v.weight": (8, 4),
        "ffn_gate.weight": (8, 16),
        "ffn_up.weight": (8, 16),
        "ffn_down.weight": (16, 8),
        "nextn.eh_proj.weight": (16, 8),
        "nextn.enorm.weight": (8,),
        "nextn.hnorm.weight": (8,),
    }
    return {"blk.2." + key: value for key, value in shapes.items()}


def test_valid_mtp_sidecar_with_own_fallback_tensors(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    p = tmp_path / "sidecar.gguf"
    shaped_fixture(p, tensors)
    result = inspect_gguf(p)
    assert result["mtp"]["representation"] == "mtp-only"
    assert result["mtp"]["status"] == "present"


def test_sidecar_missing_fallback_is_unknown(tmp_path):
    p = tmp_path / "sidecar.gguf"
    shaped_fixture(p, valid_mtp_tensors())
    result = inspect_gguf(p)
    assert result["mtp"]["representation"] == "mtp-only"
    assert result["mtp"]["status"] == "unknown"
    assert "fallback" in result["mtp"]["reason"]


@pytest.mark.parametrize("case", ["duplicate", "count", "index", "truncated"])
def test_bad_split_sets_are_invalid(tmp_path, case):
    paths = [tmp_path / f"model-{i + 1:05d}-of-00002.gguf" for i in range(2)]
    for i, path in enumerate(paths):
        tensors = {("same" if case == "duplicate" else f"tensor{i}"): (8,)}
        extra = {
            "split.no": 0 if case == "index" else i,
            "split.count": 2,
            "split.tensors.count": 3 if case == "count" else 2,
        }
        shaped_fixture(path, tensors, extra)
    if case == "truncated":
        paths[1].write_bytes(paths[1].read_bytes()[:-32])
    assert inspect_gguf(paths[0])["mtp"]["status"] == "invalid"


def test_bundled_fallback_shape_is_checked(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update({"blk.0.attn_norm.weight": (8,), "token_embd.weight": (8, 32), "output_norm.weight": (7,)})
    p = tmp_path / "bundle.gguf"
    shaped_fixture(p, tensors)
    result = inspect_gguf(p)
    assert result["mtp"]["status"] == "invalid"
    assert "output_norm.weight" in result["mtp"]["reason"]


def test_unexpected_nextn_block_is_invalid(tmp_path):
    tensors = valid_mtp_tensors()
    tensors["blk.1.nextn.enorm.weight"] = (8,)
    p = tmp_path / "bad-index.gguf"
    shaped_fixture(p, tensors)
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def test_partial_separate_qkv_with_fused_is_invalid(tmp_path):
    tensors = valid_mtp_tensors()
    tensors["blk.2.attn_qkv.weight"] = (8, 24)
    del tensors["blk.2.attn_k.weight"]
    p = tmp_path / "mixed.gguf"
    shaped_fixture(p, tensors)
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def test_invalid_head_metadata_is_invalid(tmp_path):
    p = tmp_path / "bad-heads.gguf"
    shaped_fixture(p, valid_mtp_tensors(), {"qwen35.attention.head_count": 0})
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def test_unsupported_tensor_encoding_is_unknown(tmp_path):
    p = tmp_path / "unsupported.gguf"
    shaped_fixture(p, {"tensor": (8,)})
    data = p.read_bytes()
    marker = s("tensor") + struct.pack("<IQ", 1, 8)
    at = data.index(marker) + len(marker)
    p.write_bytes(data[:at] + struct.pack("<I", 999) + data[at + 4 :])
    assert inspect_gguf(p)["mtp"]["status"] == "unknown"
    assert "unsupported tensor encoding" in inspect_gguf(p)["mtp"]["reason"]


def test_split_with_tensors_on_both_shards(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    items = list(tensors.items())
    for i in range(2):
        shaped_fixture(
            tmp_path / f"model-{i + 1:05d}-of-00002.gguf",
            dict(items[i::2]),
            {"split.no": i, "split.count": 2, "split.tensors.count": len(items)},
        )
    assert inspect_gguf(tmp_path / "model-00002-of-00002.gguf")["mtp"]["status"] == "present"


def test_unknown_nextn_tensor_does_not_claim_complete(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
            "blk.2.nextn.future.weight": (8,),
        }
    )
    p = tmp_path / "unknown-nextn.gguf"
    shaped_fixture(p, tensors)
    assert inspect_gguf(p)["mtp"]["status"] == "unknown"


def test_unequal_attention_head_dimensions_are_invalid(tmp_path):
    p = tmp_path / "bad-dimensions.gguf"
    shaped_fixture(p, valid_mtp_tensors(), {"qwen35.attention.value_length": 5})
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def test_unequal_head_dimensions_rejected_even_with_matching_v_shape(tmp_path):
    tensors = valid_mtp_tensors()
    tensors["blk.2.attn_v.weight"] = (8, 5)
    p = tmp_path / "unequal-heads.gguf"
    shaped_fixture(p, tensors, {"qwen35.attention.value_length": 5})
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def rewrite_offset(path, name, dims, offset):
    data = bytearray(path.read_bytes())
    descriptor = s(name) + struct.pack("<I", len(dims))
    descriptor += b"".join(struct.pack("<Q", dimension) for dimension in dims)
    descriptor += struct.pack("<I", 1)
    start = data.index(descriptor) + len(descriptor)
    previous = struct.unpack_from("<Q", data, start)[0]
    struct.pack_into("<Q", data, start, offset)
    path.write_bytes(data)
    return previous


@pytest.mark.parametrize(
    ("target", "offset"),
    [
        ("blk.2.post_attention_norm.weight", 0),
        ("blk.2.ffn_down.weight", 32),
        ("blk.2.nextn.enorm.weight", 0),
    ],
)
def test_public_inspector_rejects_overlapping_payloads(tmp_path, target, offset):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    p = tmp_path / "overlap.gguf"
    shaped_fixture(p, tensors)
    rewrite_offset(p, target, tensors[target], offset)
    result = inspect_gguf(p)
    assert result["mtp"]["status"] == "invalid"
    assert "overlap" in result["mtp"]["reason"]


@pytest.mark.parametrize("case", ["gap", "reordered"])
def test_public_inspector_rejects_unverified_payload_layout(tmp_path, case):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    p = tmp_path / f"{case}.gguf"
    shaped_fixture(p, tensors)
    names = list(tensors)
    if case == "gap":
        previous = 0
        for name, dims in tensors.items():
            if name == names[-1]:
                break
            previous = (previous + module.payload_bytes(dims, 1) + 31) // 32 * 32
        rewrite_offset(p, names[-1], tensors[names[-1]], previous + 32)
        p.write_bytes(p.read_bytes() + b"\0" * 32)
    else:
        rewrite_offset(p, names[2], tensors[names[2]], 0)
    result = inspect_gguf(p)
    assert result["mtp"]["status"] in {"unknown", "invalid"}
    if case == "gap":
        assert "ordering or gap" in result["mtp"]["reason"]


def test_identical_offsets_in_separate_shards_are_independent(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    entries = list(tensors.items())
    for index in range(2):
        shaped_fixture(
            tmp_path / f"model-{index + 1:05d}-of-00002.gguf",
            dict(entries[index::2]),
            {"split.no": index, "split.count": 2, "split.tensors.count": len(entries)},
        )
    result = inspect_gguf(tmp_path / "model-00002-of-00002.gguf")
    assert result["mtp"]["status"] == "present"


def test_overlap_inside_one_split_shard_invalidates_combined_model(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    entries = list(tensors.items())
    paths = [tmp_path / f"model-{index + 1:05d}-of-00002.gguf" for index in range(2)]
    for index in range(2):
        shaped_fixture(
            paths[index],
            dict(entries[index::2]),
            {"split.no": index, "split.count": 2, "split.tensors.count": len(entries)},
        )
    target, dims = entries[2]
    rewrite_offset(paths[0], target, dims, 0)
    assert inspect_gguf(paths[1])["mtp"]["status"] == "invalid"


def test_malformed_file_without_mtp_metadata_is_not_absent(tmp_path):
    p = tmp_path / "truncated-no-mtp.gguf"
    fixture(p, {"general.architecture": "qwen35"}, [])
    p.write_bytes(p.read_bytes()[:-2])
    assert inspect_gguf(p)["mtp"]["status"] == "invalid"


def test_overlap_between_mtp_and_trunk_tensor_is_invalid(tmp_path):
    tensors = valid_mtp_tensors()
    tensors.update(
        {
            "blk.0.attn_norm.weight": (8,),
            "blk.2.nextn.embed_tokens.weight": (8, 32),
            "blk.2.nextn.shared_head_head.weight": (8, 32),
            "blk.2.nextn.shared_head_norm.weight": (8,),
        }
    )
    p = tmp_path / "trunk-overlap.gguf"
    shaped_fixture(p, tensors)
    rewrite_offset(p, "blk.2.nextn.enorm.weight", (8,), 0)
    result = inspect_gguf(p)
    assert result["mtp"]["status"] == "invalid"
    assert "overlap" in result["mtp"]["reason"]
