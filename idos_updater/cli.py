"""
Konzolové rozhraní (CLI) pro IDOS Updater.
Vhodné pro automatizaci, skripty nebo uživatele preferující příkazový řádek.
"""

import sys
import os
import argparse
from typing import List

# Nastavení kódování konzole pro správné zobrazení diakritiky
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from idos_updater.core import (
    ChapsScraper,
    IdosEnvironment,
    ConfigManager,
    BackupManager,
    UpdateManager,
    PRESETS,
    UpdateItem
)


def print_banner():
    print("=" * 65)
    print("           IDOS Updater (CHAPS) - Konzole           ")
    print("=" * 65)


def list_items(items: List[UpdateItem], search_query: str = ""):
    filtered = items
    if search_query:
        q = search_query.lower()
        filtered = [it for it in items if q in it.filename.lower() or q in it.title.lower() or q in it.description.lower()]

    print(f"\nNalezeno {len(filtered)} položek:")
    print("-" * 65)
    print(f"{'Soubor':<16} | {'Datum':<11} | {'Velikost':<14} | Název")
    print("-" * 65)

    current_cat = ""
    for it in filtered:
        cat = it.category_label
        if cat != current_cat:
            current_cat = cat
            print(f"\n>>> {current_cat} <<<")

        print(f"{it.filename:<16} | {it.date:<11} | {it.size_str:<14} | {it.title}")
    print("-" * 65)


def run_cli(args: argparse.Namespace):
    config_mgr = ConfigManager()
    cfg = config_mgr.load_config()

    idos_path = args.path or cfg.get("idos_path") or r"C:\IDOS"
    idos_path = os.path.abspath(idos_path)

    print_banner()
    print(f"Cílová složka IDOS: {idos_path}")

    # Inicializace scraperu
    scraper = ChapsScraper()
    print("Připojuji se k https://www.chaps.cz a stahuji seznam aktualizací...")
    try:
        items = scraper.fetch_updates()
        print(f"Úspěšně načteno {len(items)} dostupných balíčků z CHAPS.")
    except Exception as e:
        print(f"CHYBA: Nepodařilo se stáhnout seznam z chaps.cz: {e}")
        sys.exit(1)

    # Režim: Výpis / Hledání
    if args.list or args.search:
        list_items(items, search_query=args.search or "")
        return

    # Určení položek k aktualizaci
    selected_items: List[UpdateItem] = []

    if args.preset:
        preset_key = args.preset.lower()
        if preset_key not in PRESETS:
            print(f"Neznámý preset '{args.preset}'. Dostupné: {', '.join(PRESETS.keys())}")
            sys.exit(1)
        preset_info = PRESETS[preset_key]
        print(f"\nZvolený preset: {preset_info['name']}")
        print(f"Popis: {preset_info['description']}")
        selected_items = [it for it in items if preset_info['filter'](it)]
    elif args.files:
        requested_files = [f.strip().upper() for f in args.files]
        item_map = {it.filename.upper(): it for it in items}
        for rf in requested_files:
            if rf in item_map:
                selected_items.append(item_map[rf])
            else:
                print(f"Upozornění: Soubor '{rf}' nebyl nalezen v nabídce aktualizací.")
    elif args.check:
        print("\nKontrola dostupnosti IDOS:")
        is_running = IdosEnvironment.is_idos_running()
        print(f"Stav procesu TT.exe: {'BĚŽÍ' if is_running else 'Neběží'}")
        tt_exe = os.path.join(idos_path, "TT.exe")
        print(f"Instalace IDOS: {'Nalezena (' + tt_exe + ')' if os.path.isfile(tt_exe) else 'Nenalezena v ' + idos_path}")
        return

    if not selected_items:
        print("\nNebyly vybrány žádné položky k aktualizaci.")
        print("Použijte např.: --preset quick NEBO --preset komplet NEBO --files TTAKT.ZIP VLAK26E.ZIP")
        print("Pro seznam všech položek použijte: --list")
        return

    print(f"\nPoložky určené k instalaci ({len(selected_items)}):")
    total_size = sum(it.size_bytes for it in selected_items)
    for it in selected_items:
        print(f"  • {it.filename} ({it.size_str}) - {it.title}")
    print(f"Celková velikost ke stažení: {total_size / 1024 / 1024:.2f} MB")

    # Kontrola běžícího IDOS
    if IdosEnvironment.is_idos_running():
        print("\n[!] Upozornění: IDOS (TT.exe) právě běží!")
        if args.kill_running or cfg.get("auto_kill_idos", True):
            print("Ukončuji běžící proces IDOS...")
            if IdosEnvironment.kill_idos():
                print("✓ IDOS byl úspěšně ukončen.")
            else:
                print("✗ Nepodařilo se ukončit proces IDOS. Před pokračováním jej prosím zavřete manuálně.")
                if not args.non_interactive:
                    input("Stiskněte Enter po zavření IDOS...")
        else:
            print("Před aktualizací prosím zavřete program IDOS.")
            if not args.non_interactive:
                input("Stiskněte Enter po zavření IDOS...")

    # Potvrzení před spuštěním pokud není non-interactive
    if not args.non_interactive and not args.yes:
        resp = input("\nChcete pokračovat v aktualizaci? (A/n): ").strip().lower()
        if resp and resp not in ('a', 'ano', 'y', 'yes'):
            print("Aktualizace byla přerušena.")
            return

    # Zálohování
    do_backup = args.backup if args.backup is not None else cfg.get("create_backup", True)
    if do_backup and os.path.isdir(idos_path) and os.listdir(idos_path):
        print("\nVytvářím zálohu předchozí verze IDOS...")
        backup_file = BackupManager.create_backup(idos_path, log_callback=lambda msg: print(f"  {msg}"))
        if backup_file:
            print(f"✓ Záloha vytvořena: {backup_file}")

    # Aktualizace
    print("\nZačínám stahování a instalaci balíčků...")
    updater = UpdateManager(idos_path)

    def log_cb(msg):
        print(f"  {msg}")

    def progress_cb(item, dl_bytes, total_bytes, ratio, speed_str):
        pct = int(ratio * 100) if ratio > 0 else 0
        bar_len = 25
        filled = int(bar_len * ratio) if ratio > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r  [{bar}] {pct:3d}% | {speed_str:<10} | {item.filename}")
        sys.stdout.flush()
        if dl_bytes >= total_bytes and total_bytes > 0:
            sys.stdout.write("\n")

    success_cnt, err_cnt, errors = updater.download_and_extract(
        items=selected_items,
        progress_callback=progress_cb,
        log_callback=log_cb
    )

    print("\n" + "=" * 65)
    if err_cnt == 0:
        print(f"✓ VŠECHNO HOTOVO! Úspěšně nainstalováno {success_cnt} balíčků.")
    else:
        print(f"⚠ Aktualizace dokončena s chybami: {success_cnt} úspěšných, {err_cnt} chyb.")
        for err in errors:
            print(f"  ✗ {err}")
    print("=" * 65)

    # Uložení nastavení
    cfg["idos_path"] = idos_path
    if args.preset:
        cfg["active_preset"] = args.preset.lower()
    config_mgr.save_config(cfg)

    # Spuštění IDOS po aktualizaci
    should_launch = args.launch if args.launch is not None else cfg.get("launch_after_update", False)
    if should_launch:
        print(f"Spouštím IDOS z {idos_path} ...")
        if IdosEnvironment.launch_idos(idos_path):
            print("✓ IDOS spuštěn.")
        else:
            print("✗ Nepodařilo se spustit IDOS (TT.exe nebyl nalezen).")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IDOS Updater - Automatická aktualizace aplikace a dat IDOS CHAPS."
    )
    parser.add_argument("--web", action="store_true", help="Spustí lokální webové rozhraní")
    parser.add_argument("--path", "-p", help="Cesta k instalaci IDOS (např. C:\\IDOS)")
    parser.add_argument("--list", "-l", action="store_true", help="Zobrazí všechny dostupné aktualizace")
    parser.add_argument("--search", "-s", help="Vyhledá aktualizace podle klíčového slova (např. Brno, Vlaky)")
    parser.add_argument("--check", "-c", action="store_true", help="Zkontroluje stav instalace a běžícího IDOS")
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        help=f"Výběr přednastavené sady: {', '.join(PRESETS.keys())}"
    )
    parser.add_argument("--files", "-f", nargs="+", help="Konkrétní názvy souborů ke stažení (např. TTAKT.ZIP VLAK26E.ZIP)")
    parser.add_argument("--backup", action="store_true", default=None, help="Vytvořit zálohu před aktualizací")
    parser.add_argument("--no-backup", action="store_false", dest="backup", help="Nevytvářet zálohu")
    parser.add_argument("--kill-running", action="store_true", help="Automaticky ukončit běžící TT.exe")
    parser.add_argument("--launch", action="store_true", default=None, help="Spustit IDOS po úspěšné aktualizaci")
    parser.add_argument("--yes", "-y", action="store_true", help="Automaticky potvrdit výzvy")
    parser.add_argument("--non-interactive", action="store_true", help="Bezkontaktní režim pro naplánované úlohy")
    return parser


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    run_cli(args)
