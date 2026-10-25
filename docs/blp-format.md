# Warcraft III textures: how `.blp` really works

`w3xmpq` can render `.blp` textures inline. This is the story of the
format — including the part nobody documents.

## The three families

A `.blp` file starts with a four-byte magic: `BLP1` or `BLP2`.

### BLP1 classic (pre-1.22)

| offset | field |
|---|---|
| `0x00` | magic `BLP1` |
| `0x04` | encoding — `0` uncompressed, `1` palettised |
| `0x08` | alpha depth |
| `0x0C` | width |
| `0x10` | height |
| `0x14` | extra flags |
| `0x18` | alpha encoding |
| `0x1C` | mipmap offsets ×16 |
| `0x5C` | mipmap sizes ×16 |
| `0x9C` | palette (256 × 4 bytes) |

Uncompressed pixels are 32-bit **BGRA**, stored **bottom-up** (the last
row in the file is the top row on screen).

### BLP2 classic

Same idea, 160-byte header: encoding `0` = uncompressed, `1` = DXT1,
`2` = DXT3, `3` = DXT5. The mipmap table starts at `0x20` (some tools
put it at `0x1C` — `w3xmpq` tries both and keeps whichever chains
consistently against the file length).

`w3xmpq` decodes DXT1/DXT3/DXT5 itself, in pure Python, including the
four-bit explicit alpha of DXT3 and the interpolated alpha of DXT5.

## The interesting one: BLP1 with a JPEG inside

Every texture shipped with Warcraft III 1.22 and newer — the loading
screens, the icons, the minimaps inside maps — is **not** raw pixels.
It is a **JPEG**, and the file is laid out so that the JPEG frame
header is *split in two*.

Look at the bytes:

```
0x00  42 4C 50 31        "BLP1"
0x04  00 00 00 00        encoding = 0
0x0C  00 02 00 00        width  = 512
0x10  00 01 00 00        height = 256
0x1C  9C 04 00 00        mipmap 0 offset = 1180 (0x49C)
0x5C  AB 01 00 00        mipmap 0 size
0x9C  70 02 00 00        JPEG header size = 624
0xA0  FF D8 FF E0 ...    <-- JPEG SOI, right here
      ...  FF C4 00 01 A2 ...   (DHT)
      ...  FF C0 00 00 00 00 ...  (zeroed-out placeholder!)
0x49A  00 14              <-- frame length, but 20 bytes later
0x49C  08 01 00 01 00 04 01 11 00 02 11 00 03 11 00 04 11 00
      FF DA 00 0E ...     <-- SOS, then the entropy data, then EOI
```

Three things are unusual:

1. **The header block is stored in the space where the palette would
   be.** The field at `0x9C` gives its size (624 bytes here), and the
   JPEG starts right after at `0xA0`.

2. **The frame header is torn apart.** The `FF C0` marker closes the
   shared header block, but the frame *length* (`00 14` = 20) and the
   frame *body* (precision, width, height and the four component
   records) live at the start of **every mipmap**. The bytes between
   them are zero padding.

3. **There is exactly one `FF D8` (SOI) in the whole file** — but ten
   `FF D9` (EOI) markers, one per mipmap. All mipmap levels share the
   same quantisation and Huffman tables.

### Reassembling a valid JPEG

To turn one mipmap back into a decodable JPEG, stitch the two halves
together:

```python
jpeg = data[0xA0:0xA0 + jpeg_header_size]   # SOI … DHT … FF C0 marker
jpeg += data[mipmap_offset : mipmap_offset + mipmap_size]  # len + body + SOS + scan + EOI
```

The result starts with `FF D8` and ends with `FF D9`, and any standard
JPEG decoder reads it. (Blizzard's own encoder was the *Intel JPEG
Library 6.0*, which is visible in the file's comment marker.)

### Why four components?

The frame header declares four components with 1×1 sampling — i.e. a
**CMYK** JPEG. Image libraries that only support greyscale and YCbCr
reject it outright, which is why most tools simply say "unsupported
format" for these files. Convert CMYK → RGB and the picture comes out
perfectly: the loading screens, the minimaps, the icons.

Qt's JPEG plugin *does* accept it (it decodes to `Format_CMYK8888`),
which is what the `w3xmpq` GUI uses. The CLI writes the reconstructed
stream straight to a `.jpg` file, or converts it to PNG when Pillow is
installed.

## Mipmaps

The mipmap chain is a normal halving chain: 512×256, 256×128, 128×64 …
down to 1×1. Each level has its own frame body (so its own size) but
shares the tables.

## Using it

```bash
# GUI: click any .blp in the file table
w3xmpq gui map.w3x

# CLI: full-size texture to PNG
w3xmpq blp texture.blp -o texture.png

# CLI: a smaller mipmap level as JPEG (no Pillow needed)
w3xmpq blp texture.blp -o small.jpg --level 3
```

```python
from w3xmpq.core.blp import open_blp

blp = open_blp(data)
print(blp.kind, blp.width, blp.height, len(blp.mipmaps))
blob = blp.jpeg_bytes(0)      # a valid JPEG stream
png = blp.png_bytes(0)        # PNG for the classic formats
```
