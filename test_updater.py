"""
Testovací skript pro IDOS Updater - ověření funkčnosti scraperu, stahování, extrakce a zálohování.
"""

import os
import sys
import shutil
import tempfile

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from idos_updater.core import (
    ChapsScraper,
    UpdateManager,
    BackupManager,
    IdosEnvironment,
    ConfigManager,
    PRESETS
)

def run_tests():
    print("=== TEST 1: CHAPS Web Scraper ===")
    scraper = ChapsScraper()
    items = scraper.fetch_updates()
    print(f"✓ Načteno {len(items)} položek z chaps.cz")
    assert len(items) > 100, "Scraper by měl načíst více než 100 balíčků."

    # Ověření klíčových souborů
    filenames = {it.filename.upper(): it for it in items}
    assert "TTAKT.ZIP" in filenames, "TTAKT.ZIP musí být v seznamu"
    assert "KOMPLET.ZIP" in filenames, "KOMPLET.ZIP musí být v seznamu"
    assert "VLAK26E.ZIP" in filenames, "VLAK26E.ZIP musí být v seznamu"
    print("✓ Klíčové balíčky (TTAKT, KOMPLET, VLAK26E) úspěšně identifikovány.")

    # Ověření dekódování diakritiky
    komplet = filenames["KOMPLET.ZIP"]
    print(f"✓ KOMPLET kategorie: {komplet.category_label}, popis: {komplet.description[:40]}...")
    assert "Jízdní" in komplet.section or "řády" in komplet.section or "Jízdní" in komplet.title

    print("\n=== TEST 2: Stahování a extrakce do testovací složky ===")
    temp_idos_dir = tempfile.mkdtemp(prefix="idos_test_")
    try:
        print(f"Testovací složka: {temp_idos_dir}")
        
        # Otestujeme extrakci TTAKT.ZIP (ověření odstranění App/ prefixu)
        ttakt_item = filenames["TTAKT.ZIP"]
        updater = UpdateManager(temp_idos_dir)
        
        success, err, errors = updater.download_and_extract(
            items=[ttakt_item],
            log_callback=lambda msg: print(f"  [LOG] {msg}")
        )
        assert success == 1 and err == 0, f"Instalace TTAKT selhala: {errors}"
        
        # Zkontrolujeme, zda TT.exe a TT.dll jsou přímo v kořenu testovací složky (ne v App/)
        tt_exe_path = os.path.join(temp_idos_dir, "TT.exe")
        tt_dll_path = os.path.join(temp_idos_dir, "TT.dll")
        assert os.path.isfile(tt_exe_path), f"TT.exe chybí v kořenu: {os.listdir(temp_idos_dir)}"
        assert os.path.isfile(tt_dll_path), "TT.dll chybí v kořenu"
        print(f"✓ TT.exe správně rozbalen přímo do kořene ({os.path.getsize(tt_exe_path)} B).")
        
        # Otestujeme extrakci datového archivu (např. BENESOV.ZIP -> Data3/Benesov.tt)
        benesov_item = filenames.get("BENESOV.ZIP")
        if benesov_item:
            success2, err2, errors2 = updater.download_and_extract(
                items=[benesov_item],
                log_callback=lambda msg: print(f"  [LOG] {msg}")
            )
            assert success2 == 1, "Instalace BENESOV selhala"
            benesov_tt = os.path.join(temp_idos_dir, "Data3", "Benesov.tt")
            assert os.path.isfile(benesov_tt), f"Data3/Benesov.tt chybí: {os.listdir(temp_idos_dir)}"
            print(f"✓ Datový soubor Data3/Benesov.tt správně rozbalen se zachováním podsložek.")

        print("\n=== TEST 3: Zálohování ===")
        backup_zip = BackupManager.create_backup(temp_idos_dir, log_callback=lambda msg: print(f"  [BACKUP] {msg}"))
        assert backup_zip and os.path.isfile(backup_zip), "Záloha se nevytvořila"
        print(f"✓ Záložní archiv úspěšně vytvořen: {backup_zip} ({os.path.getsize(backup_zip)} B)")

        print("\n=== TEST 4: Správa konfigurace ===")
        cfg_mgr = ConfigManager(config_file=os.path.join(temp_idos_dir, "test_config.json"))
        cfg = cfg_mgr.load_config()
        cfg["idos_path"] = temp_idos_dir
        cfg["active_preset"] = "quick"
        cfg_mgr.save_config(cfg)
        loaded = cfg_mgr.load_config()
        assert loaded["idos_path"] == temp_idos_dir
        assert loaded["active_preset"] == "quick"
        print("✓ Konfigurační manažer funguje správně.")

        print("\n========================================================")
        print("🎉 VŠECHNY TESTY PROBĚHLY ÚSPĚŠNĚ A BEZ CHYB!")
        print("========================================================")
    finally:
        shutil.rmtree(temp_idos_dir, ignore_errors=True)

if __name__ == "__main__":
    run_tests()
