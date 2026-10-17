# contracts/ — v3 hand-offs between roles

**Status: DRAFT v3. Lock at H1.** After H1, change only through [CLAUDE.md §7.3](../CLAUDE.md#73-changing-a-contract-after-h1): one-line ack from every consumer, bump `v`, regenerate types, one `contracts:` commit.

JSON Schema draft 2020-12. Every schema carries `"v": 3` (the record uses `record_version: 3`). Conventions (scan frame, raw ARKit vs OpenCV poses, intrinsics, units) are in [ARCHITECTURE.md §2](../ARCHITECTURE.md#2-conventions-locked-at-h1). Field-level summary: [ARCHITECTURE.md §9](../ARCHITECTURE.md#9-contracts-v3).

| Schema | Producer → consumers |
|---|---|
| [common.schema.json](common.schema.json) | Shared `$defs`: uuid, vec3, mat3, mat4, prob, bp, classes, decisions, class_probs |
| [capture_manifest.schema.json](capture_manifest.schema.json) | C → A, B (pose = **raw ARKit**; K in saved-JPEG pixels) |
| [recognition.schema.json](recognition.schema.json) | A → C, D, stage |
| [passport.schema.json](passport.schema.json) | A → B, D (poses = **OpenCV**, scan frame) |
| [reference_set.schema.json](reference_set.schema.json) | A → B (`data/refs/{model_key}/refs.json`, with sources) |
| [registration.schema.json](registration.schema.json) | B → D, stage |
| [registration_progress.schema.json](registration_progress.schema.json) | B → stage (snap animation) |
| [region.schema.json](region.schema.json) | B → D |
| [verdict.schema.json](verdict.schema.json) | B → D |
| [identity.schema.json](identity.schema.json) | B → D, stage |
| [price_band.schema.json](price_band.schema.json) | D → web |
| [statement.schema.json](statement.schema.json) | D → web |
| [deal.schema.json](deal.schema.json) | web → D (`POST /deals`) |
| [handover_result.schema.json](handover_result.schema.json) | D → web |
| [record.schema.json](record.schema.json) | D → verify page (**the signed object: integers and strings only**) |
| [realtime_event.schema.json](realtime_event.schema.json) | everyone → web; also the demo JSONL line format |
| [constants/price_v3.json](constants/price_v3.json) | D → backend + web ("How is this priced?"); also holds decision thresholds |
| [test-vectors/record_v3.json](test-vectors/record_v3.json) | Canonical JSON + SHA-256 vector |

## Canonical JSON (signed objects)

UTF-8 · keys sorted · separators `,` `:` with no spaces · ASCII keys · **no floats, no nulls** (omit optional fields).

- Python: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
- JS: `const canon = v => Array.isArray(v) ? "[" + v.map(canon).join(",") + "]" : (v && typeof v === "object") ? "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}" : JSON.stringify(v);`
- Swift: sort keys with `JSONEncoder.OutputFormatting.sortedKeys` **and** `.withoutEscapingSlashes`; integers only. Prove it against the vector at H1–H4.
- **Vector:** `test-vectors/record_v3.json` → sha256 `68b71c27aebcf7fd65edb2bf10cb0b6d9caf9f3b7db4ede61fa5867b9d6acab2`. Checked during planning: Python and Node agree, the record validates against `record.schema.json`, and a float in it is rejected.
- Signatures: Ed25519 over the **raw 32-byte** hash; CryptoKit (seller, iPhone), tweetnacl (buyer, browser), PyNaCl (server verify).

## Generating types (H1, D)

- Python: `datamodel-codegen --input contracts --input-file-type jsonschema --output backend/contracts/models.py --output-model-type pydantic_v2.BaseModel`
- TypeScript: `json-schema-to-typescript` → `web/lib/contracts.ts`
- Swift: hand-written `Codable` in `ios/Mint/Contracts/` for the manifest, recognition and scan responses, tested against JSON fixtures.
- Commit generated files; never hand-edit them.
