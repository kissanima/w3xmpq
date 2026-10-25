---
name: Bug report
about: Report a broken archive / wrong extraction
labels: bug
---

**Archive type**
- [ ] WC3 map (.w3x/.w3m)
- [ ] Plain MPQ
- [ ] Other/unknown

**What happened?**
<!-- e.g. extraction fails / file X is corrupted / key not recovered -->

**Evidence** (do NOT attach the map itself — attach command output)
```
$ w3xmpq list <archive> --json
<paste output>

$ w3xmpq extract <archive> -o out --json
<paste output>
```

**Environment**
- OS:
- Python version (or binary release):

**Anything else that might help** (flags, archive origin, size)
