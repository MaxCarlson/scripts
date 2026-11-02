# P15a GGUF MTP structural inspection

Branch: `agent/local-inference-p15a-20261102`. This read-only inspector reports
MTP structure, not backend capability or a validated inference result. It does
not validate the entire Qwen trunk, tensor values, tokenizer semantics, or
compatibility between separately supplied files. `present` means that the
supported MTP inventory, shapes, payload bounds and locally available fallback
shapes passed; it is not a claim that the whole model can run.

On 2026-11-02, inspection of the installed `lmstudio-community/Qwen3.8-27B-GGUF`
Q4_K_M and Q6_K files classified both `present`, `bundled`. Each has 866 tensor descriptors and 39 metadata entries; the complete tensor
table passes bounded payload-range, native descriptor-order, alignment-padding,
and file-bound checks. Both have block count 65, one NextN layer at index 64, embedding 5120, FFN 17408, 24 query
heads, 4 KV heads and key/value head dimensions 256. Their MTP tensor shapes
are: Q (5120, 12288); K and V (5120, 1024); attention output (6144, 5120);
Q/K norms (256); FFN gate/up (5120, 17408), down (17408, 5120); eh projection
(10240, 5120); MTP norms and shared head norm (5120). Both contain
`token_embd.weight` and `output.weight` of (5120, 248320), and
`output_norm.weight` of (5120). These supply local fallback tensors where
NextN-specific embedding/head tensors are absent. Runtime support remains
unverified; no model was loaded and no inference was performed.

The inspector supports conventional numbered split filenames, checks split
metadata and tensor uniqueness/counts, and checks bounds, overlap, descriptor
order, and alignment padding independently in each shard. Proven range overlap
is invalid. Non-overlapping gaps or reordered descriptors are unknown as an
unsupported layout. Nonconforming shard names, unsupported GGML encodings, additional
NextN tensor kinds, missing shape metadata, and sidecars needing external
fallback tensors remain `unknown`. In particular, no sidecar/trunk pair
compatibility is asserted. Parsing is bounded to 64 MiB of tables per shard,
one million aggregate tensors, and 10,000 shards. Layout validation reads descriptors only; it does not read tensor
payload contents and does not establish weight-byte integrity. Only Qwen35 with one appended
NextN layer is supported. A trunk-only classification does not certify that
its trunk is complete. GGUF validity outside the inspected structural checks
is not established.

P15b can use these results as a structural preflight that fails closed on
`unknown` or `invalid`; a frozen profile contract and independent backend,
load, and runtime capability verification remain prerequisites to any adapter
or live experiment. No production configuration or service was changed.

References: [Qwen35 loader](https://github.com/ggml-org/llama.cpp/blob/master/src/models/qwen35.cpp),
[GGUF format](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md).
