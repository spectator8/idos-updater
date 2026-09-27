import sys
import os
import argparse
from typing import List

# Nastavenie kódovania konzoly pre správne zobrazenie diakritiky
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
    print("           IDOS Updater (CHAPS) - Konzola           ")
    print("=" * 65)


def list_items(items: List[UpdateItem], search_query: str = ""):
    filtered = items
    if search_query:
        q = search_query.lower()
        filtered = [it for it in items if q in it.filename.lower() or q in it.title.lower() or q in it.description.lower()]

    print(f"\nNájdených {len(filtered)} položiek:")
    print("-" * 65)
    print(f"{'Súbor':<16} | {'Dátum':<11} | {'Veľkosť':<14} | Názov")
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
    print(f"Cieľový priečinok IDOS: {idos_path}")

    # Inicializácia scrapera
    scraper = ChapsScraper()
    print("Pripájam sa k https://www.chaps.cz a sťahujem zoznam aktualizácií...")
    try:
        items = scraper.fetch_updates()
        print(f"Úspešne načítaných {len(items)} dostupných balíčkov z CHAPS.")
    except Exception as e:
        print(f"CHYBA: Nepodarilo sa stiahnuť zoznam z chaps.cz: {e}")
        sys.exit(1)

    # Režim: Listovanie / Hľadanie
    if args.list or args.search:
        list_items(items, search_query=args.search or "")
        return

    # Určenie položiek na aktualizáciu
    selected_items: List[UpdateItem] = []

    if args.preset:
        preset_key = args.preset.lower()
        if preset_key not in PRESETS:
            print(f"Neznámy preset '{args.preset}'. Dostupné: {', '.join(PRESETS.keys())}")
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
                print(f"Upozornenie: Súbor '{rf}' sa nenašiel v ponuke aktualizácií.")
    elif args.check:
        print("\nKontrola dostupnosti IDOS:")
        is_running = IdosEnvironment.is_idos_running()
        print(f"Stav procesu TT.exe: {'BEŽÍ' if is_running else 'Nebeží'}")
        tt_exe = os.path.join(idos_path, "TT.exe")
        print(f"Inštalácia IDOS: {'Nájdená (' + tt_exe + ')' if os.path.isfile(tt_exe) else 'Nenájdená v ' + idos_path}")
        return

    if not selected_items:
        print("\nNeboli vybrané žiadne položky na aktualizáciu.")
        print("Použite napr.: --preset quick ALEBO --preset komplet ALEBO --files TTAKT.ZIP VLAK26E.ZIP")
        print("Pre zoznam všetkých položiek použite: --list")
        return

    print(f"\nPoložky určené na inštaláciu ({len(selected_items)}):")
    total_size = sum(it.size_bytes for it in selected_items)
    for it in selected_items:
        print(f"  • {it.filename} ({it.size_str}) - {it.title}")
    print(f"Celková veľkosť na stiahnutie: {total_size / 1024 / 1024:.2f} MB")

    # Kontrola bežiaceho IDOS
    if IdosEnvironment.is_idos_running():
        print("\n[!] Upozornenie: IDOS (TT.exe) práve beží!")
        if args.kill_running or cfg.get("auto_kill_idos", True):
            print("Ukončujem bežiaci proces IDOS...")
            if IdosEnvironment.kill_idos():
                print("✓ IDOS bol úspešne ukončený.")
            else:
                print("✗ Nepodarilo sa ukončiť proces IDOS. Pred pokračovaním ho prosím zatvorte manuálne.")
                if not args.non_interactive:
                    input("Stlačte Enter po zatvorení IDOS...")
        else:
            print("Pred aktualizáciou prosím zatvorte program IDOS.")
            if not args.non_interactive:
                input("Stlačte Enter po zatvorení IDOS...")

    # Potvrdenie pred spustením ak nie je non-interactive
    if not args.non_interactive and not args.yes:
        resp = input("\nChcete pokračovať s aktualizáciou? (A/n): ").strip().lower()
        if resp and resp not in ('a', 'ano', 'y', 'yes'):
            print("Aktualizácia bola prerušená.")
            return

    # Zálohovanie
    do_backup = args.backup if args.backup is not None else cfg.get("create_backup", True)
    if do_backup and os.path.isdir(idos_path) and os.listdir(idos_path):
        print("\nVytváram zálohu predchádzajúcej verzie IDOS...")
        backup_file = BackupManager.create_backup(idos_path, log_callback=lambda msg: print(f"  {msg}"))
        if backup_file:
            print(f"✓ Záloha vytvorená: {backup_file}")

    # Aktualizácia
    print("\nZačínam sťahovanie a inštaláciu balíčkov...")
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
        print(f"✓ VŠETKO HOTOVO! Úspešne nainštalovaných {success_cnt} balíčkov.")
    else:
        print(f"⚠ Aktualizácia dokončená s chybami: {success_cnt} úspešných, {err_cnt} chýb.")
        for err in errors:
            print(f"  ✗ {err}")
    print("=" * 65)

    # Uloženie nastavení
    cfg["idos_path"] = idos_path
    if args.preset:
        cfg["active_preset"] = args.preset.lower()
    config_mgr.save_config(cfg)

    # Spustenie IDOS po aktualizácii
    should_launch = args.launch if args.launch is not None else cfg.get("launch_after_update", False)
    if should_launch:
        print(f"Spúšťam IDOS z {idos_path} ...")
        if IdosEnvironment.launch_idos(idos_path):
            print("✓ IDOS spustený.")
        else:
            print("✗ Nepodarilo sa spustiť IDOS (TT.exe sa nenašiel).")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IDOS Updater - Automatická aktualizácia aplikácie a dát IDOS CHAPS."
    )
    parser.add_argument("--path", "-p", help="Cesta k inštalácii IDOS (napr. C:\\IDOS)")
    parser.add_argument("--list", "-l", action="store_true", help="Zobrazí všetky dostupné aktualizácie")
    parser.add_argument("--search", "-s", help="Vyhľadá aktualizácie podľa kľúčového slova (napr. Brno, Vlaky)")
    parser.add_argument("--check", "-c", action="store_true", help="Skontroluje stav inštalácie a bežiaceho IDOS")
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        help=f"Výber prednastavenej sady: {', '.join(PRESETS.keys())}"
    )
    parser.add_argument("--files", "-f", nargs="+", help="Konkrétne názvy súborov na stiahnutie (napr. TTAKT.ZIP VLAK26E.ZIP)")
    parser.add_argument("--backup", action="store_true", default=None, help="Vytvoriť zálohu pred aktualizáciou")
    parser.add_argument("--no-backup", action="store_false", dest="backup", help="Nevytvárať zálohu")
    parser.add_argument("--kill-running", action="store_true", help="Automaticky ukončiť bežiaci TT.exe")
    parser.add_argument("--launch", action="store_true", default=None, help="Spustiť IDOS po úspešnej aktualizácii")
    parser.add_argument("--yes", "-y", action="store_true", help="Automaticky potvrdiť výzvy")
    parser.add_argument("--non-interactive", action="store_true", help="Bezkontaktný režim pre naplánované úlohy")
    return parser


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    run_cli(args)
