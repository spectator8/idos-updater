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
    print(f"✓ Načítaných {len(items)} položiek z chaps.cz")
    assert len(items) > 100, "Scraper by mal načítať viac ako 100 balíčkov."

    # Overenie kľúčových súborov
    filenames = {it.filename.upper(): it for it in items}
    assert "TTAKT.ZIP" in filenames, "TTAKT.ZIP musí byť v zozname"
    assert "KOMPLET.ZIP" in filenames, "KOMPLET.ZIP musí byť v zozname"
    assert "VLAK26E.ZIP" in filenames, "VLAK26E.ZIP musí byť v zozname"
    print("✓ Kľúčové balíčky (TTAKT, KOMPLET, VLAK26E) úspešne identifikované.")

    # Overenie dekódovania diakritiky
    komplet = filenames["KOMPLET.ZIP"]
    print(f"✓ KOMPLET kategória: {komplet.category_label}, popis: {komplet.description[:40]}...")
    assert "Jízdní" in komplet.section or "řády" in komplet.section or "Jízdní" in komplet.title

    print("\n=== TEST 2: Sťahovanie a extrakcia do testovacieho priečinka ===")
    temp_idos_dir = tempfile.mkdtemp(prefix="idos_test_")
    try:
        print(f"Testovací adresár: {temp_idos_dir}")
        
        # Otestujeme extrakciu TTAKT.ZIP (overenie odstránenia App/ prefixu)
        ttakt_item = filenames["TTAKT.ZIP"]
        updater = UpdateManager(temp_idos_dir)
        
        success, err, errors = updater.download_and_extract(
            items=[ttakt_item],
            log_callback=lambda msg: print(f"  [LOG] {msg}")
        )
        assert success == 1 and err == 0, f"Inštalácia TTAKT zlyhala: {errors}"
        
        # Skontrolujeme, či TT.exe a TT.dll sú priamo v koreni testovacieho priečinka (nie v App/)
        tt_exe_path = os.path.join(temp_idos_dir, "TT.exe")
        tt_dll_path = os.path.join(temp_idos_dir, "TT.dll")
        assert os.path.isfile(tt_exe_path), f"TT.exe chýba v koreni: {os.listdir(temp_idos_dir)}"
        assert os.path.isfile(tt_dll_path), "TT.dll chýba v koreni"
        print(f"✓ TT.exe správne rozbalený priamo do koreňa ({os.path.getsize(tt_exe_path)} B).")
        
        # Otestujeme extrakciu dátového archívu (napr. BENESOV.ZIP -> Data3/Benesov.tt)
        benesov_item = filenames.get("BENESOV.ZIP")
        if benesov_item:
            success2, err2, errors2 = updater.download_and_extract(
                items=[benesov_item],
                log_callback=lambda msg: print(f"  [LOG] {msg}")
            )
            assert success2 == 1, "Inštalácia BENESOV zlyhala"
            benesov_tt = os.path.join(temp_idos_dir, "Data3", "Benesov.tt")
            assert os.path.isfile(benesov_tt), f"Data3/Benesov.tt chýba: {os.listdir(temp_idos_dir)}"
            print(f"✓ Dátový súbor Data3/Benesov.tt správne rozbalený so zachovaním podadresárov.")

        print("\n=== TEST 3: Zálohovanie ===")
        backup_zip = BackupManager.create_backup(temp_idos_dir, log_callback=lambda msg: print(f"  [BACKUP] {msg}"))
        assert backup_zip and os.path.isfile(backup_zip), "Záloha sa nevytvorila"
        print(f"✓ Záložný archív úspešne vytvorený: {backup_zip} ({os.path.getsize(backup_zip)} B)")

        print("\n=== TEST 4: Správa konfigurácie ===")
        cfg_mgr = ConfigManager(config_file=os.path.join(temp_idos_dir, "test_config.json"))
        cfg = cfg_mgr.load_config()
        cfg["idos_path"] = temp_idos_dir
        cfg["active_preset"] = "quick"
        cfg_mgr.save_config(cfg)
        loaded = cfg_mgr.load_config()
        assert loaded["idos_path"] == temp_idos_dir
        assert loaded["active_preset"] == "quick"
        print("✓ Konfiguračný manažér funguje správne.")

        print("\n========================================================")
        print("🎉 VŠETKY TESTY PREBEHLI ÚSPEŠNE A BEZ CHÝB!")
        print("========================================================")
    finally:
        shutil.rmtree(temp_idos_dir, ignore_errors=True)

if __name__ == "__main__":
    run_tests()
