"""CR-010.R1 conformance corpus — static fixtures + declarative case manifest.

The corpus is an **interop artifact**, not a GraQle-internal test helper. Every
case is a committed static JSON file plus a declarative expectation in
``corpus-manifest.json``. A third-party verifier implementation consumes those
files over a subprocess/JSON boundary and must classify every case identically
to be called conformant — it never imports GraQle code.

See ``../proof-spec/v1.0/SPEC.md`` for the normative envelope and the
conformance procedure.
"""

from __future__ import annotations
