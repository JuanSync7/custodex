---
cdm:
  fingerprint: 518fd0083e23694a
  fingerprint_tiers:
    composite: 518fd0083e23694a
    docstring: f72661bf34f59eec
    signature: 759bc168e8ad0a7f
  region_anchors:
    symbols:
    - 652bcc3a47842889
    - 7dd7a28c2ff9e308
    - a6b7e556f733a02c
    - a6b7e556f733a02c
    - d15ba48afa285e4a
  region_hashes:
    overview: 7349bcdbe8928433
    symbols: 5d48cc43ef1cfbef
  symbol_sigs:
    652bcc3a47842889: ecd3240014b8e586
    7dd7a28c2ff9e308: 10e56c211bb15307
    a6b7e556f733a02c: 19bcb95ed91d520f
    d15ba48afa285e4a: ff556e6f7a54220e
title: Model
---

# Model

> The fixture data models: an `Item` record and a resizable `Widget`.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Item | class | class Item(BaseModel) |
| Widget | class | class Widget |
| Widget.__init__ | method | def __init__(self, size: int = 1) -> None |
| Widget.size | method | def size(self) -> int |
| Widget.size | method | def size(self, value: int) -> None |
<!-- CDM:END symbols -->

## Overview

<!-- CDM:BEGIN overview -->
Hand-written overview: an `Item` carries a price, and a `Widget` can be
resized through its `size` property.
<!-- CDM:END overview -->
