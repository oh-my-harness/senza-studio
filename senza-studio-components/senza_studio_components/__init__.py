"""Senza Studio Components — shared prefab tools + capability components.

v1 is a static pip package (no marketplace yet — see senza-studio's design
doc §10: "先做静态 pip 包...推广后再做市场"). Studio installs this package
into its own venv and reads from `senza_studio_components.registry` at
Play time; it is not per-project.
"""
