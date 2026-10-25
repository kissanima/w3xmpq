# Deprotection patterns

How WC3 map protection works, and what `w3xmpq report` says about each
pattern. All of these are "game-lenient, editor-hostile": the game still
runs the map, but the official World Editor refuses to open it.

## 1. Script relocation (the classic)

The map's real script is placed at the game's *fallback* path
`Scripts\war3map.j`, and the canonical `war3map.j` is deleted. The game
resolves `war3map.j` → `Scripts\war3map.j` at load time; World Editor only
reads the canonical name.

```
[!] Script moved to fallback path (high)
```

Fix: rename `Scripts\war3map.j` back to `war3map.j`. w3xmpq extracts the
fallback script as `war3map_script.j`, ready to rename.

## 2. Anti-tamper stub

The canonical `war3map.j` is replaced by a tiny script (~244 bytes) that
disables single-player and ends the game, e.g. containing
`Disabled Single Player` / `EndGame(true)`.

```
[!] Canonical script is an anti-tamper stub (high)
```

Fix: replace it with the fallback script (see pattern 1).

## 3. Authoring-file deletion (script-only maps)

World Editor needs the authoring files to open a map. Deleting them makes
the map script-only:

| File | Purpose |
|---|---|
| `war3map.wtg` | trigger GUI database |
| `war3map.wct` | trigger custom text |
| `war3map.imp` | imported files list |
| `war3map.w3t` | item object data |
| `war3map.w3q` | upgrade object data |
| `war3map.w3u` | unit object data |
| `war3mapUnits.doo` | preplaced units |

```
[!] Authoring files missing (editor-hostile) (high)
```

Fix: re-add minimal (even empty) versions of the missing files. Script-only
maps spawn everything via script, so stubs are usually enough to open —
but the map will look "empty" in the editor's trigger/object panes.

## 4. Decoy listfile

The archive contains a `(listfile)` that is binary junk (or plain lies),
meant to confuse tools that trust it.

```
[*] Decoy (listfile) (warning)
```

Fix: none needed — w3xmpq never trusts the listfile; it recovers names via
hash-probing and content sniffing.

## 5. Metadata-inconsistent decoy blocks

Blocks whose block-table size field contradicts the stored data (e.g. a
fake `(listfile)` claiming 481 bytes with only 206 stored). Some are
encrypted with old-codec flags (PKWARE implode).

w3xmpq extracts what is actually stored and notes the inconsistency in the
unknown-block analysis (entropy + magic sniffing).

## Ethics

Deprotection is for recovering maps **you own** (authors who lost their
source), studying map formats, and preservation. Re-publishing someone
else's protected map as your own is theft — don't.
