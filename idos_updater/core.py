"""
Jádro aplikace IDOS Updater.
Obsahuje třídy pro stahování seznamu aktualizací z chaps.cz,
správu prostředí IDOS, porovnávání verzí/dat souborů, manifest instalovaných balíčků,
zálohování, stahování archivů a detailní hlášení chyb při extrakci.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import subprocess
import urllib.request
import urllib.error
import html
import re
import datetime
import traceback
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Callable, Tuple, Set, Any
from pathlib import Path


CHAPS_URL = "https://www.chaps.cz/cs/download/idos"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 IDOSUpdater/1.0"
MANIFEST_FILENAME = "_installed_manifest.json"


def parse_date(date_str: str) -> datetime.date:
    """Převede textové datum (např. '25.9.2026') na objekt datetime.date."""
    try:
        parts = [int(p) for p in date_str.strip().split('.')]
        return datetime.date(parts[2], parts[1], parts[0])
    except Exception:
        return datetime.date(1970, 1, 1)


@dataclass
class UpdateItem:
    filename: str
    title: str
    description: str
    section: str
    subsection: str
    date: str
    size_str: str
    size_bytes: int
    url: str

    @property
    def category_label(self) -> str:
        if self.subsection:
            return f"{self.section} - {self.subsection}"
        return self.section

    @property
    def is_program(self) -> bool:
        return self.filename.upper() in ("TTAKT.ZIP", "TTOLD.ZIP", "TTFONT.ZIP")

    @property
    def is_komplet(self) -> bool:
        return self.filename.upper() == "KOMPLET.ZIP"

    @property
    def parsed_date(self) -> datetime.date:
        return parse_date(self.date)

    def get_target_signatures(self) -> Tuple[List[str], List[str]]:
        """
        Vrátí (seznam_souborů, seznam_složek), které tento balíček typicky instaluje.
        Používá se pro spolehlivou detekci přítomnosti balíčku na disku.
        """
        files = []
        dirs = []
        fn_upper = self.filename.upper()
        base = self.filename.rsplit('.', 1)[0].lower()

        if fn_upper in ("TTAKT.ZIP", "TTOLD.ZIP"):
            files.extend(["tt.exe", "tt.dll", "ttc.dll"])
        elif fn_upper == "TTFONT.ZIP":
            files.extend(["tt.ttf", "instfont.exe"])
        elif fn_upper == "KOMPLET.ZIP":
            files.extend(["vlak26e.tt", "bus26c.tt", "vlak26c.tt"])
        elif fn_upper in ("C1.ZIP", "C2.ZIP", "CODIS.ZIP", "CPID.ZIP"):
            dirs.append(base)

        # Hledání všech možných přípon z popisu (.tt, .ttm, .ttr, .tar, .map, .exe, .dll, atd.)
        found = re.findall(r'([A-Za-z0-9_]+\.(?:tt[mr]?|exe|dll|ttf|map|tar|prt|chm|ini|txt|htm|html))', self.description, re.IGNORECASE)
        for f in found:
            files.append(f.lower())

        # Standardní varianty přípon pro základní název
        for ext in (".tt", ".ttm", ".ttr", ".tar", ".map"):
            files.append(f"{base}{ext}")
            if base.endswith('_m'):
                files.append(f"{base[:-2]}.ttm")
                files.append(f"{base[:-2]}.map")
            if base.endswith('_p'):
                files.append(f"{base[:-2]}.tar")
                files.append(f"{base[:-2]}.ttr")

        # Odstranění duplicit se zachováním pořadí
        clean_files = list(dict.fromkeys(files))
        clean_dirs = list(dict.fromkeys(dirs))
        return clean_files, clean_dirs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateItem":
        return cls(**data)


def decode_chaps_text(text: str) -> str:
    """Dekóduje HTML entity generované z bajtových hodnot Windows-1250 do správného Unicode."""
    def repl(m):
        code = int(m.group(1))
        if code < 256:
            try:
                return bytes([code]).decode('cp1250')
            except Exception:
                return chr(code)
        return chr(code)

    text = re.sub(r'&#(\d+);', repl, text)
    text = html.unescape(text)
    return text


class ManifestManager:
    """Spravuje JSON manifest nainstalovaných balíčků v cílové složce IDOS."""

    @classmethod
    def get_manifest_path(cls, idos_path: str) -> str:
        return os.path.join(idos_path, MANIFEST_FILENAME)

    @classmethod
    def load_manifest(cls, idos_path: str) -> Dict[str, Any]:
        p = cls.get_manifest_path(idos_path)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Chyba při čtení manifestu: {e}")
        return {}

    @classmethod
    def record_installation(cls, idos_path: str, item: UpdateItem, extracted_files: List[str]):
        manifest = cls.load_manifest(idos_path)
        manifest[item.filename.upper()] = {
            "date": item.date,
            "installed_at": datetime.datetime.now().isoformat(),
            "files": [os.path.relpath(f, idos_path) for f in extracted_files]
        }
        p = cls.get_manifest_path(idos_path)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Chyba při zápisu manifestu: {e}")


class ChapsScraper:
    """Stahuje a zpracovává seznam dostupných aktualizací z chaps.cz."""

    def __init__(self, url: str = CHAPS_URL):
        self.url = url

    def parse_size_bytes(self, size_str: str) -> int:
        clean = re.sub(r'[^\d]', '', size_str)
        return int(clean) if clean else 0

    def fetch_updates(self, timeout: int = 20) -> List[UpdateItem]:
        req = urllib.request.Request(
            self.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "cs,sk;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_bytes = resp.read()
            html_text = content_bytes.decode('utf-8', errors='replace')

        decoded_html = decode_chaps_text(html_text)
        return self.parse_html(decoded_html)

    def parse_html(self, html_text: str) -> List[UpdateItem]:
        items: List[UpdateItem] = []
        current_section = "Všeobecné"
        current_subsection = ""

        pattern = re.compile(
            r'(<h3[^>]*>.*?</h3>|<h4[^>]*>.*?</h4>|<div class="productListItem">.*?</div>\s*</div>)',
            re.DOTALL | re.IGNORECASE
        )

        for match in pattern.finditer(html_text):
            block = match.group(1)
            if block.startswith('<h3') or block.startswith('<H3'):
                raw_title = re.sub(r'<[^>]+>', '', block).strip()
                title = html.unescape(raw_title)
                if title and not any(title.startswith(ignore) for ignore in [
                    'Důležité', 'Obsah', 'Postup', 'Upozornění', 'Poznámka', 'Důležitá', 'Navigace', 'Nabídka'
                ]):
                    current_section = title
                    current_subsection = ""
            elif block.startswith('<h4') or block.startswith('<H4'):
                raw_sub = re.sub(r'<[^>]+>', '', block).strip()
                current_subsection = html.unescape(raw_sub)
            elif 'productListItem' in block:
                link_m = re.search(r'href=["\'](https?://[^"\']+\.ZIP)["\']', block, re.IGNORECASE)
                if not link_m:
                    continue
                download_url = link_m.group(1)
                filename = download_url.split('/')[-1]

                title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL | re.IGNORECASE)
                title_val = ""
                if title_m:
                    raw_h2 = re.sub(r'<[^>]+>', '', title_m.group(1))
                    title_val = html.unescape(raw_h2).replace('více informací', '').replace('vice informaci', '').strip()

                desc_m = re.search(r'<p><strong>(.*?)</strong>(.*?)<p>Datum', block, re.DOTALL | re.IGNORECASE)
                if not desc_m:
                    desc_m = re.search(r'<p><strong>(.*?)</strong>', block, re.DOTALL | re.IGNORECASE)
                    main_desc = html.unescape(re.sub(r'<[^>]+>', '', desc_m.group(1))).strip() if desc_m else ""
                    extra_desc = ""
                else:
                    main_desc = html.unescape(re.sub(r'<[^>]+>', '', desc_m.group(1))).strip()
                    extra_desc = html.unescape(re.sub(r'<[^>]+>', ' ', desc_m.group(2))).strip()

                full_desc = main_desc
                if extra_desc:
                    full_desc = f"{main_desc} ({extra_desc})"

                date_m = re.search(r'Datum aktualizace:\s*<strong>([^<]+)</strong>', block, re.IGNORECASE)
                date_val = date_m.group(1).strip() if date_m else ""

                size_m = re.search(r'velikost:\s*<strong>([^<]+)</strong>', block, re.IGNORECASE)
                size_val = size_m.group(1).strip() if size_m else ""
                size_bytes = self.parse_size_bytes(size_val)

                items.append(UpdateItem(
                    filename=filename,
                    title=title_val or filename,
                    description=full_desc,
                    section=current_section,
                    subsection=current_subsection,
                    date=date_val,
                    size_str=size_val,
                    size_bytes=size_bytes,
                    url=download_url
                ))

        return items


class IdosEnvironment:
    """Poskytuje informace o lokální instalaci IDOS, detekci verzí a procesech."""

    POSSIBLE_PATHS = [
        r"C:\IDOS",
        r"C:\Program Files (x86)\CHAPS\IDOS",
        r"C:\Program Files\CHAPS\IDOS",
        r"D:\IDOS",
        r"E:\IDOS",
        os.path.join(os.path.expanduser("~"), "IDOS"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "IDOS")
    ]

    @classmethod
    def find_default_path(cls) -> Optional[str]:
        for path in cls.POSSIBLE_PATHS:
            if os.path.isdir(path):
                if os.path.isfile(os.path.join(path, "TT.exe")) or os.path.isdir(os.path.join(path, "Data1")):
                    return os.path.abspath(path)
        return None

    @classmethod
    def scan_local_files(cls, idos_path: str) -> Dict[str, Any]:
        """
        Prohledá složku IDOS a vrátí strukturu:
        {
          'files': { 'vlak26e.tt': (plná_cesta, datetime.date), ... },
          'dirs': { 'c1': (plná_cesta, datetime.date), ... },
          'manifest': { 'PLZEN_M.ZIP': { 'date': '1.9.2026', ... } }
        }
        """
        files_map: Dict[str, Tuple[str, datetime.date]] = {}
        dirs_map: Dict[str, Tuple[str, datetime.date]] = {}
        manifest = {}

        if not idos_path or not os.path.isdir(idos_path):
            return {'files': files_map, 'dirs': dirs_map, 'manifest': manifest}

        manifest = ManifestManager.load_manifest(idos_path)

        try:
            for root, dirnames, filenames in os.walk(idos_path):
                if "_backups" in root or "backups" in root:
                    continue
                for d in dirnames:
                    full_d = os.path.join(root, d)
                    try:
                        mtime = os.path.getmtime(full_d)
                        dt = datetime.date.fromtimestamp(mtime)
                        dirs_map[d.lower()] = (full_d, dt)
                    except Exception:
                        pass
                for fn in filenames:
                    full_p = os.path.join(root, fn)
                    try:
                        mtime = os.path.getmtime(full_p)
                        dt = datetime.date.fromtimestamp(mtime)
                        files_map[fn.lower()] = (full_p, dt)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Chyba při skenování lokálních souborů: {e}")

        return {'files': files_map, 'dirs': dirs_map, 'manifest': manifest}

    @classmethod
    def get_item_update_status(cls, item: UpdateItem, scan_result: Dict[str, Any], log_callback: Optional[Callable[[str], None]] = None) -> Tuple[str, str, Optional[str]]:
        """Vrátí stav balíčku.

        Now checks *all* files listed in the manifest and logs the matching
        filenames (only when a logger is supplied)."""
        files_map = scan_result.get('files', {})
        dirs_map = scan_result.get('dirs', {})
        manifest = scan_result.get('manifest', {})

        item_date = item.parsed_date
        fn_key = item.filename.upper()

        # 1️⃣ Manifest check – any file from the manifest must exist (case‑insensitive)
        if fn_key in manifest:
            record = manifest[fn_key]
            rec_date_str = record.get("date", "")
            rec_date = parse_date(rec_date_str) if rec_date_str else None
            rec_files = record.get("files", [])

            # verify existence (case‑insensitive)
            existing = [
                f for f in rec_files
                if os.path.basename(f).lower() in files_map
            ]
            if log_callback:
                log_callback(
                    f"🔎 Manifest check for {fn_key}: {len(existing)}/{len(rec_files)} files present"
                )
            if existing:
                if rec_date and item_date > rec_date:
                    return ("outdated", "🟠 Vyžaduje aktualizaci", rec_date_str)
                return ("up_to_date", "🟢 Aktuální", rec_date_str or item.date)

        # 2️⃣ Signature‑based detection
        file_targets, dir_targets = item.get_target_signatures()

        found_dates = []
        for tgt in file_targets:
            if tgt in files_map:
                _, local_dt = files_map[tgt]
                found_dates.append(local_dt)

        for d_tgt in dir_targets:
            if d_tgt in dirs_map:
                _, local_dt = dirs_map[d_tgt]
                found_dates.append(local_dt)

        if not found_dates:
            return ("not_installed", "⚪ Nenainstalováno", None)

        latest_local_dt = max(found_dates)
        local_date_str = f"{latest_local_dt.day}.{latest_local_dt.month}.{latest_local_dt.year}"

        if item_date > latest_local_dt:
            return ("outdated", "🟠 Vyžaduje aktualizaci", local_date_str)
        else:
            return ("up_to_date", "🟢 Aktuální", local_date_str)

    @classmethod
    def is_idos_running(cls) -> bool:
        """Zjistí, zda běží proces TT.exe."""
        if os.name != 'nt':
            return False
        try:
            cmd = ['tasklist', '/FI', 'IMAGENAME eq TT.exe', '/NH', '/FO', 'CSV']
            output = subprocess.check_output(cmd, creationflags=0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0).decode('cp1250', errors='ignore')
            return "TT.exe" in output or "tt.exe" in output
        except Exception:
            return False

    @classmethod
    def kill_idos(cls) -> bool:
        """Ukončí proces TT.exe."""
        if not cls.is_idos_running():
            return True
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'TT.exe'], check=True, creationflags=0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            time.sleep(0.5)
            return not cls.is_idos_running()
        except Exception:
            return False

    @classmethod
    def launch_idos(cls, idos_path: str) -> bool:
        """Spustí program IDOS (TT.exe)."""
        exe_path = os.path.join(idos_path, "TT.exe")
        if not os.path.isfile(exe_path):
            return False
        try:
            subprocess.Popen([exe_path], cwd=idos_path)
            return True
        except Exception as e:
            print(f"Chyba při spuštění IDOS: {e}")
            return False


class ConfigManager:
    """Spravuje uživatelská nastavení v JSON konfiguračním souboru."""

    def __init__(self, config_file: Optional[str] = None):
        if config_file:
            self.config_file = config_file
        else:
            appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
            conf_dir = os.path.join(appdata, "IDOS_Updater")
            os.makedirs(conf_dir, exist_ok=True)
            self.config_file = os.path.join(conf_dir, "config.json")

    def load_config(self) -> dict:
        default_config = {
            "idos_path": IdosEnvironment.find_default_path() or r"C:\IDOS",
            "create_backup": True,
            "launch_after_update": False,
            "auto_kill_idos": True,
            "active_preset": "quick",
            "selected_custom_files": []
        }
        if os.path.isfile(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_config.update(data)
            except Exception as e:
                print(f"Chyba při načítání konfigurace: {e}")
        return default_config

    def save_config(self, config: dict):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Chyba při ukládání konfigurace: {e}")


class BackupManager:
    """Vytváří zálohu složky IDOS před aktualizací."""

    @classmethod
    def create_backup(cls, idos_path: str, backup_dir: Optional[str] = None, log_callback: Optional[Callable[[str], None]] = None) -> Optional[str]:
        if not os.path.isdir(idos_path):
            if log_callback:
                log_callback(f"Složka {idos_path} neexistuje, záloha přeskočena.")
            return None

        if backup_dir is None:
            backup_dir = os.path.join(idos_path, "_backups")

        os.makedirs(backup_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_zip = os.path.join(backup_dir, f"idos_backup_{timestamp}.zip")

        if log_callback:
            log_callback(f"Vytvářím zálohu do: {backup_zip} ...")

        try:
            with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(idos_path):
                    if os.path.abspath(root).startswith(os.path.abspath(backup_dir)):
                        continue
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, idos_path)
                        zipf.write(full_path, rel_path)

            if log_callback:
                size_mb = os.path.getsize(backup_zip) / (1024 * 1024)
                log_callback(f"Záloha úspěšně dokončena ({size_mb:.2f} MB).")
            return backup_zip
        except Exception as e:
            if log_callback:
                log_callback(f"Chyba při vytváření zálohy: {e}")
            return None


class UpdateManager:
    """Řídí proces stahování a extrakce balíčků s podrobným hlášením chyb."""

    def __init__(self, idos_path: str):
        self.idos_path = idos_path

    def download_and_extract(
        self,
        items: List[UpdateItem],
        progress_callback: Optional[Callable[[UpdateItem, int, int, float, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[int, int, List[str]]:
        """
        Stáhne a rozbalí vybrané položky.
        Vrátí: (úspěšné_položky, chybné_položky, seznam_detailních_chyb)
        """
        os.makedirs(self.idos_path, exist_ok=True)
        success_count = 0
        error_count = 0
        errors = []

        total_items = len(items)
        for idx, item in enumerate(items, start=1):
            if cancel_check and cancel_check():
                if log_callback:
                    log_callback("Aktualizace byla zrušena uživatelem.")
                break

            if log_callback:
                log_callback(f"[{idx}/{total_items}] Stahuji {item.filename} ({item.size_str}) - {item.title} ...")

            try:
                req = urllib.request.Request(item.url, headers={"User-Agent": USER_AGENT})
                start_time = time.time()
                downloaded = 0
                chunks = []

                with urllib.request.urlopen(req, timeout=35) as resp:
                    total_bytes = int(resp.headers.get('content-length', item.size_bytes or 0))
                    while True:
                        if cancel_check and cancel_check():
                            break
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start_time
                        speed_bps = downloaded / elapsed if elapsed > 0 else 0
                        speed_str = f"{speed_bps / 1024 / 1024:.2f} MB/s" if speed_bps > 1024*1024 else f"{speed_bps / 1024:.1f} KB/s"
                        if progress_callback:
                            progress_callback(item, downloaded, total_bytes, (downloaded / total_bytes) if total_bytes > 0 else 0, speed_str)

                if cancel_check and cancel_check():
                    break

                zip_data = b''.join(chunks)
                if log_callback:
                    log_callback(f"Rozbaluji {item.filename} do {self.idos_path} ...")

                # Extrakce a zápis
                extracted_files = self._extract_zip(item.filename, zip_data, log_callback)

                # Záznam do manifestu
                ManifestManager.record_installation(self.idos_path, item, extracted_files)

                success_count += 1
                if log_callback:
                    log_callback(f"✓ {item.filename} úspěšně nainstalován ({len(extracted_files)} souborů).")

            except urllib.error.HTTPError as he:
                error_count += 1
                err_msg = f"Chyba sítě u {item.filename}: HTTP {he.code} ({he.reason}) na adrese {item.url}"
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"❌ {err_msg}")
            except urllib.error.URLError as ue:
                error_count += 1
                err_msg = f"Chyba připojení u {item.filename}: {ue.reason}"
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"❌ {err_msg}")
            except PermissionError as pe:
                error_count += 1
                err_msg = f"Přístup odepřen při zápisu {item.filename} ({pe}). Soubor je pravděpodobně uzamčen běžícím programem IDOS (TT.exe)."
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"❌ {err_msg}")
            except zipfile.BadZipFile:
                error_count += 1
                err_msg = f"Poškozený archiv {item.filename} (stažený soubor není platný ZIP)."
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"❌ {err_msg}")
            except Exception as e:
                error_count += 1
                err_msg = f"Neočekávaná chyba u {item.filename}: {type(e).__name__} - {e}"
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"❌ {err_msg}\n    {traceback.format_exc()}")

        return success_count, error_count, errors

    def _extract_zip(self, filename: str, zip_data: bytes, log_callback: Optional[Callable[[str], None]] = None) -> List[str]:
        """Rozbalí ZIP archiv a vrátí seznam plných cest všech extrahovaných souborů."""
        import io
        is_ttakt = (filename.upper() == "TTAKT.ZIP")
        extracted_paths = []

        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            for member in z.infolist():
                if member.is_dir():
                    continue

                member_name = member.filename
                if member_name.startswith("./") or member_name.startswith(".\\"):
                    member_name = member_name[2:]

                # Špeciální pravidlo pro TTAKT.ZIP: CHAPS ukládá soubory do složky App/,
                # ale patří přímo do kořenové složky IDOS!
                if is_ttakt:
                    if member_name.lower().startswith("app/") or member_name.lower().startswith("app\\"):
                        member_name = member_name[4:]

                target_file_path = os.path.join(self.idos_path, os.path.normpath(member_name))
                target_dir = os.path.dirname(target_file_path)
                os.makedirs(target_dir, exist_ok=True)

                with z.open(member) as source_f, open(target_file_path, "wb") as dest_f:
                    shutil.copyfileobj(source_f, dest_f)

                extracted_paths.append(target_file_path)

        return extracted_paths


# Přednastavené sady aktualizací (Presety)
PRESETS = {
    "quick": {
        "name": "⚡ Rychlá aktualizace (Program + Vlaky + Busy)",
        "description": "Aktualizuje spustitelný program (TTAKT), písmo (TTFONT), vlaky ČR/Evropa a autobusy ČR/SR.",
        "filter": lambda item: item.filename.upper() in (
            "TTAKT.ZIP", "TTFONT.ZIP", "VLAK26E.ZIP", "VLAK26C.ZIP", "BUS26C.ZIP", "BUS26S.ZIP"
        )
    },
    "komplet": {
        "name": "📦 Kompletní aktualizace (Program + KOMPLET.ZIP)",
        "description": "Stáhne program a kompletní archiv všech jízdních řádů (vlaky, busy, MHD).",
        "filter": lambda item: item.filename.upper() in ("TTAKT.ZIP", "TTFONT.ZIP", "KOMPLET.ZIP")
    },
    "trains_buses": {
        "name": "🚆 Pouze Vlaky a Autobusy",
        "description": "Aktualizuje všechny vlakové a autobusové linky (ČR, SR, Evropa).",
        "filter": lambda item: item.filename.upper() in (
            "VLAK26E.ZIP", "VLAK26C.ZIP", "VLAKPID26.ZIP", "BUS26C.ZIP", "BUS26CK.ZIP", "BUS26CKD.ZIP", "BUS26S.ZIP"
        )
    },
    "program_only": {
        "name": "⚙️ Pouze Program (TTAKT + TTFONT)",
        "description": "Aktualizuje pouze samotný prohlížeč IDOS a systémové písmo.",
        "filter": lambda item: item.filename.upper() in ("TTAKT.ZIP", "TTFONT.ZIP")
    },
    "all_individual": {
        "name": "🌐 Všechny dostupné balíčky jednotlivě",
        "description": "Aktualizuje všechny balíčky včetně všech MHD měst, map a tarifů (kromě TTOLD a KOMPLET).",
        "filter": lambda item: item.filename.upper() not in ("TTOLD.ZIP", "KOMPLET.ZIP")
    }
}
