import os
from pathlib import Path
from vdedup.hashers import partial_hash, sha256_file

def test_partial_hash_head_tail(tmp_path: Path):
    p = tmp_path / "f.bin"
    data = b"A" * (1024 * 1024) + b"B" * (1024 * 1024) + b"C" * (1024 * 1024)
    p.write_bytes(data)
    head, tail, mid, algo = partial_hash(p, head_bytes=512*1024, tail_bytes=512*1024, mid_bytes=0)
    assert head and tail
    assert mid is None
    assert algo in ("blake3", "blake2b")

def test_sha256_block_size(tmp_path: Path):
    p = tmp_path / "f2.bin"
    p.write_bytes(os.urandom(2 * 1024 * 1024))
    h1 = sha256_file(p, 1 << 16)
    h2 = sha256_file(p, 1 << 20)
    assert h1 == h2
