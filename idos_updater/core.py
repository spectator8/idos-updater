"""
Jadro aplikácie IDOS Updater.
Obsahuje triedy pre sťahovanie zoznamu aktualizácií z chaps.cz,
správu IDOS prostredia, zálohovanie, sťahovanie archívov a ich extrakciu.
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
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Callable, Tuple
from pathlib import Path


CHAPS_URL = "https://www.chaps.cz/cs/download/idos"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 IDOSUpdater/1.0"


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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateItem":
        return cls(**data)


def decode_chaps_text(text: str) -> str:
    """Dekóduje HTML entity generované z Windows-1250 byte hodnôt do správneho Unicode."""
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


class ChapsScraper:
    """Sťahuje a spracováva zoznam dostupných aktualizácií z chaps.cz."""

    def __init__(self, url: str = CHAPS_URL):
        self.url = url

    def parse_size_bytes(self, size_str: str) -> int:
        """Prevedie napr. '1.975.168 B' alebo '76.850 B' na celé číslo bajtov."""
        clean = re.sub(r'[^\d]', '', size_str)
        return int(clean) if clean else 0

    def fetch_updates(self, timeout: int = 20) -> List[UpdateItem]:
        """Stiahne webovú stránku a vráti zoznam položiek."""
        req = urllib.request.Request(
            self.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "sk,cs;q=0.9,en;q=0.8",
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

        # Hľadáme h3, h4 a productListItem
        pattern = re.compile(
            r'(<h3[^>]*>.*?</h3>|<h4[^>]*>.*?</h4>|<div class="productListItem">.*?</div>\s*</div>)',
            re.DOTALL | re.IGNORECASE
        )

        for match in pattern.finditer(html_text):
            block = match.group(1)
            if block.startswith('<h3') or block.startswith('<H3'):
                raw_title = re.sub(r'<[^>]+>', '', block).strip()
                title = html.unescape(raw_title)
                # Ignorujeme informačné hlavičky na začiatku
                if title and not any(title.startswith(ignore) for ignore in [
                    'Důležité', 'Obsah', 'Postup', 'Upozornění', 'Poznámka', 'Důležitá', 'Navigace', 'Nabídka'
                ]):
                    current_section = title
                    current_subsection = ""
            elif block.startswith('<h4') or block.startswith('<H4'):
                raw_sub = re.sub(r'<[^>]+>', '', block).strip()
                current_subsection = html.unescape(raw_sub)
            elif 'productListItem' in block:
                # Odkaz na stiahnutie
                link_m = re.search(r'href=["\'](https?://[^"\']+\.ZIP)["\']', block, re.IGNORECASE)
                if not link_m:
                    continue
                download_url = link_m.group(1)
                filename = download_url.split('/')[-1]

                # Názov
                title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL | re.IGNORECASE)
                title_val = ""
                if title_m:
                    raw_h2 = re.sub(r'<[^>]+>', '', title_m.group(1))
                    title_val = html.unescape(raw_h2).replace('více informací', '').replace('vice informaci', '').strip()

                # Popis
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

                # Dátum aktualizácie
                date_m = re.search(r'Datum aktualizace:\s*<strong>([^<]+)</strong>', block, re.IGNORECASE)
                date_val = date_m.group(1).strip() if date_m else ""

                # Veľkosť
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
    """Poskytuje informácie o lokálnej inštalácii IDOS a procesoch."""

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
    def is_idos_running(cls) -> bool:
        """Zistí, či beží proces TT.exe."""
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
            print(f"Chyba pri spustení IDOS: {e}")
            return False


class ConfigManager:
    """Spravuje používateľské nastavenia v JSON konfiguračnom súbore."""

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
                print(f"Chyba pri načítaní konfigurácie: {e}")
        return default_config

    def save_config(self, config: dict):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Chyba pri ukladaní konfigurácie: {e}")


class BackupManager:
    """Vytvára zálohu IDOS adresára pred aktualizáciou."""

    @classmethod
    def create_backup(cls, idos_path: str, backup_dir: Optional[str] = None, log_callback: Optional[Callable[[str], None]] = None) -> Optional[str]:
        if not os.path.isdir(idos_path):
            if log_callback:
                log_callback(f"Adresár {idos_path} neexistuje, záloha preskočená.")
            return None

        if backup_dir is None:
            backup_dir = os.path.join(idos_path, "_backups")

        os.makedirs(backup_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_zip = os.path.join(backup_dir, f"idos_backup_{timestamp}.zip")

        if log_callback:
            log_callback(f"Vytváram zálohu do: {backup_zip} ...")

        try:
            with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(idos_path):
                    # Preskočíme adresár so zálohami, aby sme nezálohovali zálohy
                    if os.path.abspath(root).startswith(os.path.abspath(backup_dir)):
                        continue
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, idos_path)
                        zipf.write(full_path, rel_path)

            if log_callback:
                size_mb = os.path.getsize(backup_zip) / (1024 * 1024)
                log_callback(f"Záloha úspešne dokončená ({size_mb:.2f} MB).")
            return backup_zip
        except Exception as e:
            if log_callback:
                log_callback(f"Chyba pri vytváraní zálohy: {e}")
            return None


class UpdateManager:
    """Riadi proces sťahovania a extrakcie balíčkov."""

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
        Stiahne a rozbalí vybrané položky.
        Vráti: (úspešné_položky, chybné_položky, zoznam_chýb)
        """
        os.makedirs(self.idos_path, exist_ok=True)
        success_count = 0
        error_count = 0
        errors = []

        total_items = len(items)
        for idx, item in enumerate(items, start=1):
            if cancel_check and cancel_check():
                if log_callback:
                    log_callback("Aktualizácia bola zrušená používateľom.")
                break

            if log_callback:
                log_callback(f"[{idx}/{total_items}] Sťahujem {item.filename} ({item.size_str}) - {item.title} ...")

            try:
                # Sťahovanie do dočasného súboru alebo pamäte
                req = urllib.request.Request(item.url, headers={"User-Agent": USER_AGENT})
                start_time = time.time()
                downloaded = 0
                chunks = []

                with urllib.request.urlopen(req, timeout=30) as resp:
                    total_bytes = int(resp.headers.get('content-length', item.size_bytes or 0))
                    while True:
                        if cancel_check and cancel_check():
                            break
                        chunk = resp.read(65536) # 64 KB chunk
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
                    log_callback(f"Rozbaľujem {item.filename} do {self.idos_path} ...")

                # Extrakcia
                self._extract_zip(item.filename, zip_data, log_callback)
                success_count += 1
                if log_callback:
                    log_callback(f"✓ {item.filename} úspešne nainštalovaný.")

            except Exception as e:
                error_count += 1
                err_msg = f"Chyba pri inštalácii {item.filename}: {e}"
                errors.append(err_msg)
                if log_callback:
                    log_callback(f"✗ {err_msg}")

        return success_count, error_count, errors

    def _extract_zip(self, filename: str, zip_data: bytes, log_callback: Optional[Callable[[str], None]] = None):
        """Rozbalí ZIP archív a správne ošetrí špeciálne cesty ako TTAKT (App/ -> root)."""
        import io
        is_ttakt = (filename.upper() == "TTAKT.ZIP")

        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            for member in z.infolist():
                if member.is_dir():
                    continue

                member_name = member.filename
                # Odstránenie ./ na začiatku
                if member_name.startswith("./") or member_name.startswith(".\\"):
                    member_name = member_name[2:]

                # Špeciálne pravidlo pre TTAKT.ZIP: CHAPS ukladá súbory do priečinka App/,
                # ale patria priamo do koreňového priečinka IDOS!
                if is_ttakt:
                    if member_name.lower().startswith("app/") or member_name.lower().startswith("app\\"):
                        member_name = member_name[4:]

                target_file_path = os.path.join(self.idos_path, os.path.normpath(member_name))
                target_dir = os.path.dirname(target_file_path)
                os.makedirs(target_dir, exist_ok=True)

                # Bezpečný zápis súboru
                with z.open(member) as source_f, open(target_file_path, "wb") as dest_f:
                    shutil.copyfileobj(source_f, dest_f)


# Prednastavené sady aktualizácií (Presety)
PRESETS = {
    "quick": {
        "name": "⚡ Rýchla aktualizácia (Program + Vlaky + Busy)",
        "description": "Aktualizuje spustiteľný program (TTAKT), písmo (TTFONT), vlaky ČR/Európa a autobusy ČR/SR.",
        "filter": lambda item: item.filename.upper() in (
            "TTAKT.ZIP", "TTFONT.ZIP", "VLAK26E.ZIP", "VLAK26C.ZIP", "BUS26C.ZIP", "BUS26S.ZIP"
        )
    },
    "komplet": {
        "name": "📦 Kompletná aktualizácia (Program + KOMPLET.ZIP)",
        "description": "Stiahne program a kompletný archív všetkých cestovných poriadkov (vlaky, busy, MHD).",
        "filter": lambda item: item.filename.upper() in ("TTAKT.ZIP", "TTFONT.ZIP", "KOMPLET.ZIP")
    },
    "trains_buses": {
        "name": "🚆 Iba Vlaky a Autobusy",
        "description": "Aktualizuje všetky vlakové a autobusové linky (ČR, SR, Európa).",
        "filter": lambda item: item.filename.upper() in (
            "VLAK26E.ZIP", "VLAK26C.ZIP", "VLAKPID26.ZIP", "BUS26C.ZIP", "BUS26CK.ZIP", "BUS26CKD.ZIP", "BUS26S.ZIP"
        )
    },
    "program_only": {
        "name": "⚙️ Iba Program (TTAKT + TTFONT)",
        "description": "Aktualizuje iba samotný prehliadač IDOS a systémové písmo.",
        "filter": lambda item: item.filename.upper() in ("TTAKT.ZIP", "TTFONT.ZIP")
    },
    "all_individual": {
        "name": "🌐 Všetky dostupné balíčky jednotlivo",
        "description": "Aktualizuje všetky balíčky vrátane všetkých MHD miest, máp a taríf (okrem TTOLD a KOMPLET).",
        "filter": lambda item: item.filename.upper() not in ("TTOLD.ZIP", "KOMPLET.ZIP")
    }
}
