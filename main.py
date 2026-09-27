#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Hlavní spouštěcí soubor aplikace IDOS Updater.
Pokud je spuštěn bez parametrů, otevře grafické rozhraní (GUI).
Pokud jsou předány argumenty příkazové řádky, provede příkaz (CLI).
"""

import os
import sys

# Přidání složky do sys.path pro přímý import
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from idos_updater.__main__ import main

if __name__ == "__main__":
    main()
