# How the w3xmpq crack works

## The problem

MPQ (MoPaQ) archives can encrypt individual files. The encryption key is
normally derived from the *filename*:

```
key = hash(filename, TABLE)            # + FIX_KEY adjustments
```

Without filenames (no listfile, or a protected map where the listfile is a
decoy), key derivation is impossible the normal way. Protected WC3 maps rely
on exactly this.

## The known-plaintext attack

Every multi-sector MPQ file starts with its **sector offset table** — the
table of where each sector's data begins within the file. Two facts make it
a known-plaintext target:

1. Its first DWORD is always the size of the table itself:
   `p0 = 4 * (sectors + 1)` — and the sector count is computable from the
   block-table entry (`block.size // sector_size + 1`, +1 with SECTOR_CRC).
2. The table must be **monotonically increasing** and its last entry must
   equal the block's `archived_size`.

## The cipher's first step

The MPQ cipher (see `src/w3xmpq/core/mpq.py`, `_decrypt`) processes 32-bit
words. For the first word:

```
seed2 = 0xEEEEEEEE + T[0x400 + (key & 0xFF)]
ct0   ^ p0 = key + seed2
```

where `T` is the 2048-entry MPQ crypt table. So for each of the 256 possible
low-byte table indexes `lb`:

```
key_candidate = (ct0 ^ p0) - 0xEEEEEEEE - T[0x400 + lb]
```

A candidate is self-consistent only if `key_candidate & 0xFF == lb` — this
usually leaves 1–2 candidates per file.

## Verification

Each candidate key is used to decrypt the whole offset table. It is accepted
only if:

- `table[0] == 4 * (sectors + 1)`,
- `table[last] == block.archived_size`,
- the table is strictly increasing.

A wrong key produces a structurally valid table with probability ~2^-64.
In practice: **1–2 candidate trials per file**, verified instantly.

## The sector key scheme (format 0/1)

With the base key recovered, decryption per sector is:

- offset table: encrypted with `key`
- data sector `i`: encrypted with `(key + i + 1) & 0xFFFFFFFF`

(the offset table occupies key slot 0). Single-unit files have no offset
table; if the filename is known via hash-probing, the standard named key is
used instead.

## The three bugs that break every naive implementation

1. **Per-sector key increments the wrong thing**: decrypting everything with
   `key + i` (instead of `key + i + 1`) or with a single key corrupts data.
2. **Zero-padding the tail**: the MPQ cipher covers only whole 4-byte words;
   the trailing `len % 4` bytes are stored as plaintext. Padding them corrupts
   compressed streams (zlib reports "incorrect data check").
3. **Assuming a compression mask byte everywhere**: unencrypted files store
   their short final sector raw, without a mask byte. w3xmpq verifies both
   interpretations against the sector's expected length.

## Results

Validated on 1,854 real files across two protected maps (DotA 6.83d AI:
1297/1297, MooMoo v3.19b: 557/559) with zero key-recovery failures.
