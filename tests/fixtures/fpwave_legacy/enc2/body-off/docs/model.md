---
cdm:
  fingerprint: 5c1dda59597f4dbd
  fingerprint_tiers:
    composite: 5c1dda59597f4dbd
    docstring: 55a9115d21932dad
    signature: b745ea25e12a3b12
  region_anchors:
    symbols:
    - 4e12cecccbeeec2d
    - 6389da0a505a4d0a
    - 652bcc3a47842889
    - 7dd7a28c2ff9e308
    - a6b7e556f733a02c
    - a6b7e556f733a02c
    - d15ba48afa285e4a
  region_hashes:
    overview: 378bccd6602348c0
    symbols: c054d882600bb27e
  symbol_sigs:
    4e12cecccbeeec2d: 8b8f8d131dfd51b9
    6389da0a505a4d0a: 27d4123be539b07d
    652bcc3a47842889: ecd3240014b8e586
    7dd7a28c2ff9e308: 10e56c211bb15307
    a6b7e556f733a02c: c1d2bf14205fc264
    d15ba48afa285e4a: ff556e6f7a54220e
title: Model
---

# Model

> The fixture data models: an `Item` record and a resizable `Widget`.

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Item | class | class Item(BaseModel) |
| Item.name | variable | name: str |
| Item.price | variable | price: float = 0.0 |
| Widget | class | class Widget |
| Widget.__init__ | method | def __init__(self, size: int = 1) -> None |
| Widget.size | method | @property def size(self) -> int |
| Widget.size | method | @size.setter def size(self, value: int) -> None |
<!-- CDM:END symbols -->

## Overview

<!-- CDM:BEGIN overview -->
Hand-written overview: an `Item` carries a price, and a `Widget` can be
resized through its `size` property.
<!-- CDM:END overview -->
