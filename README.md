# memes900k

The **memes900k** dataset: 900,000 captioned memes built from 300 image templates.

Template artwork is sourced from [memegenerator.net](https://memegenerator.net).

## Contents

The dataset ships as a single archive, `memes900k.zip` (~45 MB). Extract it first:

```bash
unzip memes900k.zip
```

That produces a `memes900k/` directory. The extracted directory is gitignored — only
the archive is tracked here, to avoid storing two copies of the same data.

| File | Rows | Description |
| --- | --- | --- |
| `memes900k/captions.txt` | 900,000 | All captions, concatenated from the three splits |
| `memes900k/captions_train.txt` | 750,000 | Training split |
| `memes900k/captions_val.txt` | 75,000 | Validation split |
| `memes900k/captions_test.txt` | 75,000 | Test split |
| `memes900k/templates.txt` | 300 | One row per template image |
| `memes900k/images/` | 300 files | Template images, named `<template-slug>.jpg` |

### Caption format

`captions.txt` and the three split files are tab-separated with three columns:

```
<template name>	<meme id>	<setup text> <sep> <punchline text>
```

Example:

```
Y U No	1145	commercial <sep> y u no same volume as show!?
```

- **template name** — matches the first column of `templates.txt`
- **meme id** — unique integer identifying the individual meme instance
- **caption** — the meme text; `<sep>` separates the setup from the punchline, so it
  can be stripped or used as a split point

### Template format

`templates.txt` is tab-separated with three columns:

```
<template name>	<url path>	<image url>
```

Example:

```
Y U No	/Y-U-No	https://memegenerator.net/img/images/300x300/166088/y-u-no.jpg
```

## Loading the data

```python
import csv

with open("memes900k/captions_train.txt", encoding="utf-8") as f:
    for template, meme_id, caption in csv.reader(f, delimiter="\t"):
        setup, _, punchline = caption.partition(" <sep> ")
        print(template, meme_id, setup, punchline)
```

## Note on `captions.txt`

`captions.txt` is the exact concatenation of `captions_train.txt`,
`captions_val.txt`, and `captions_test.txt` (750,000 + 75,000 + 75,000 = 900,000).
You can regenerate it from the splits if you would rather not read a second copy.
