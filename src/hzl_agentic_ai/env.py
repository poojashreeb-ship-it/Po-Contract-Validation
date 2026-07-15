"""Reads a required env var, stripping a leading BOM.

Observed on this project's Windows deployment pipeline: piping a secret
value through PowerShell into `vercel env add` reproducibly prepends a
U+FEFF (byte-order-mark) character to the stored value, regardless of the
encoding controls attempted on the PowerShell/.NET side (Windows PowerShell
5.1's .NET Framework has no ProcessStartInfo.StandardInputEncoding to force
a BOM-less write). Rather than depend on a clean upload pipeline, strip it
defensively wherever these values are actually used.
"""
import os


def required_env(name: str) -> str:
    return os.environ[name].lstrip("﻿")
