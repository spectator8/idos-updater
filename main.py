#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Hlavný spúšťací súbor aplikácie IDOS Updater.
Ak sa spustí bez parametrov, otvorí moderné grafické rozhranie (GUI).
Ak sa spustia argumenty príkazového riadka, vykoná príkaz (CLI).
"""

import os
import sys

# Pridanie priečinka do sys.path pre priamy import
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from idos_updater.__main__ import main

if __name__ == "__main__":
    main()
