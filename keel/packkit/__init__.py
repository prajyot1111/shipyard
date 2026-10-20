"""The pack kit (c-735): everything a code host pack does that is not about its host.

A connection to a code host is two things: how to talk to the host, and what its words are.
Everything else (the card, the cut, the draft, Ship, the sight, review cards, the brief, the
verbs, the requirement rows and the guard) is here, written once and held once. A pack on the
kit is its host layer (`layer.py` says the contract), its sentences, its rules, and one short
shim per verb that names its own folder and its layer.

A pack imports the kit through `KEEL_HOME`, which every verb, the guard and the requirement
checks are given. `VERSION` is the contract a layer declares it was written for (its `KIT`);
the kit changes only by adding, and a layer written for another version is refused in one
sentence (`layer.check_layer`). Standard library only, and nothing heavy here: the guard
imports this package on every Bash call a house makes.

docs/atlas/62-packs.md, "The pack kit", is the page.
"""

VERSION = 1
