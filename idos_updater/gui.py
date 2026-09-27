"""
Grafické rozhraní (GUI) pro IDOS Updater v knihovně Tkinter.
Umožňuje pohodlný výběr balíčků, přednastavené sady (presety), vyhledávání,
inteligentní detekci zastaralých balíčků, manifest instalace, zálohování a detailní sledování chyb.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Dict, Set, Optional, Tuple, Any

from idos_updater.core import (
    ChapsScraper,
    IdosEnvironment,
    ConfigManager,
    BackupManager,
    UpdateManager,
    UpdateItem,
    PRESETS
)


class IdosUpdaterGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IDOS Aktualizátor (CHAPS)")
        self.geometry("1020x740")
        self.minsize(850, 620)

        # Načtení konfigurace
        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.load_config()

        # Stavové proměnné
        self.items: List[UpdateItem] = []
        self.scan_result: Dict[str, Any] = {'files': {}, 'dirs': {}, 'manifest': {}}
        self.selected_filenames: Set[str] = set()
        self.is_updating = False
        self.cancel_requested = False

        # Nastavení stylu
        self._setup_styles()

        # Vytvoření uživatelského rozhraní
        self._create_widgets()

        # Inicializace cest, skenování a kontrola
        self._refresh_path_status()
        self._check_process_status()

        # Asynchronní načtení seznamu aktualizací z webu
        self.after(100, self.refresh_updates_list)

    def _setup_styles(self):
        self.style = ttk.Style(self)
        available_themes = self.style.theme_names()
        if 'clam' in available_themes:
            self.style.theme_use('clam')
        elif 'vista' in available_themes:
            self.style.theme_use('vista')

        self.style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=6)
        self.style.configure("Preset.TButton", font=("Segoe UI", 9), padding=4)
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9, "bold"))

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="10 10 10 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. HLAVIČKA A CESTA K IDOS
        path_group = ttk.LabelFrame(main_frame, text=" 📁 Instalace IDOS ", padding="8")
        path_group.pack(fill=tk.X, pady=(0, 8))

        path_top_row = ttk.Frame(path_group)
        path_top_row.pack(fill=tk.X)

        ttk.Label(path_top_row, text="Složka IDOS:").pack(side=tk.LEFT, padx=(0, 6))
        self.path_var = tk.StringVar(value=self.config.get("idos_path", r"C:\IDOS"))
        self.path_entry = ttk.Entry(path_top_row, textvariable=self.path_var, width=50)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.path_entry.bind("<KeyRelease>", lambda e: self._on_path_changed())

        ttk.Button(path_top_row, text="Procházet...", command=self._browse_path).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(path_top_row, text="Autodetekce", command=self._autodetect_path).pack(side=tk.LEFT, padx=(0, 4))
        self.launch_btn = ttk.Button(path_top_row, text="▶ Spustit IDOS", command=self._launch_idos)
        self.launch_btn.pack(side=tk.LEFT, padx=(4, 0))

        # Stavový řádek instalace a běžícího procesu
        path_status_row = ttk.Frame(path_group)
        path_status_row.pack(fill=tk.X, pady=(6, 0))

        self.path_status_label = ttk.Label(path_status_row, text="Kontrola složky...", font=("Segoe UI", 8))
        self.path_status_label.pack(side=tk.LEFT)

        self.proc_status_frame = ttk.Frame(path_status_row)
        self.proc_status_frame.pack(side=tk.RIGHT)
        self.proc_status_label = ttk.Label(self.proc_status_frame, text="", font=("Segoe UI", 8, "bold"))
        self.proc_status_label.pack(side=tk.LEFT, padx=(0, 6))
        self.kill_proc_btn = ttk.Button(self.proc_status_frame, text="Ukončit IDOS", command=self._kill_idos, width=12)

        # 2. RYCHLÉ PRESETY (TLAČÍTKA)
        preset_group = ttk.LabelFrame(main_frame, text=" ⚡ Rychlý výběr (Předvolby) ", padding="6")
        preset_group.pack(fill=tk.X, pady=(0, 8))

        preset_btn_frame = ttk.Frame(preset_group)
        preset_btn_frame.pack(fill=tk.X)

        ttk.Button(preset_btn_frame, text="⚡ Označit vyžadující aktualizaci", style="Preset.TButton",
                   command=self._select_outdated_only).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="⚪ Označit nenainstalované", style="Preset.TButton",
                   command=self._select_not_installed).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="⚡ Rychlá (Program + Vlaky + Busy)", style="Preset.TButton",
                   command=lambda: self._apply_preset("quick")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="📦 Kompletní (KOMPLET + Program)", style="Preset.TButton",
                   command=lambda: self._apply_preset("komplet")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="🚆 Pouze Vlaky & Busy", style="Preset.TButton",
                   command=lambda: self._apply_preset("trains_buses")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="⚙️ Pouze Program", style="Preset.TButton",
                   command=lambda: self._apply_preset("program_only")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="🧹 Zrušit výběr", style="Preset.TButton",
                   command=self._clear_selection).pack(side=tk.RIGHT, padx=2)

        # 3. VYHLEDÁVÁNÍ A SEZNAM BALÍČKŮ
        list_group = ttk.LabelFrame(main_frame, text=" 📦 Dostupné balíčky z CHAPS ", padding="6")
        list_group.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        filter_row = ttk.Frame(list_group)
        filter_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(filter_row, text="🔍 Filtr:").pack(side=tk.LEFT, padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_row, textvariable=self.search_var, width=22)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_tree())

        ttk.Label(filter_row, text="Kategorie:").pack(side=tk.LEFT, padx=(6, 4))
        self.category_var = tk.StringVar(value="Všechny")
        self.category_combo = ttk.Combobox(filter_row, textvariable=self.category_var, state="readonly", width=22)
        self.category_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_tree())

        ttk.Label(filter_row, text="Stav:").pack(side=tk.LEFT, padx=(6, 4))
        self.status_filter_var = tk.StringVar(value="Všechny stavy")
        self.status_combo = ttk.Combobox(
            filter_row,
            textvariable=self.status_filter_var,
            state="readonly",
            values=["Všechny stavy", "🟠 Pouze vyžadující aktualizaci", "🟢 Pouze aktuální", "⚪ Pouze nenainstalované", "🟠+⚪ Zastaralé nebo chybějící"],
            width=28
        )
        self.status_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.status_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_tree())

        ttk.Button(filter_row, text="🔄 Obnovit z webu", command=self.refresh_updates_list).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(filter_row, text="Označit zobrazené", command=self._select_all_visible).pack(side=tk.RIGHT, padx=(4, 0))

        # Tabulka / Treeview
        tree_frame = ttk.Frame(list_group)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("selected", "status", "filename", "category", "date", "size", "description")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("selected", text="✓", anchor=tk.CENTER)
        self.tree.heading("status", text="Stav verze", anchor=tk.W)
        self.tree.heading("filename", text="Soubor", anchor=tk.W)
        self.tree.heading("category", text="Kategorie", anchor=tk.W)
        self.tree.heading("date", text="Datum na webu", anchor=tk.CENTER)
        self.tree.heading("size", text="Velikost", anchor=tk.E)
        self.tree.heading("description", text="Popis / Obsah", anchor=tk.W)

        self.tree.column("selected", width=35, anchor=tk.CENTER, stretch=False)
        self.tree.column("status", width=145, anchor=tk.W, stretch=False)
        self.tree.column("filename", width=115, anchor=tk.W, stretch=False)
        self.tree.column("category", width=175, anchor=tk.W, stretch=False)
        self.tree.column("date", width=100, anchor=tk.CENTER, stretch=False)
        self.tree.column("size", width=95, anchor=tk.E, stretch=False)
        self.tree.column("description", width=340, anchor=tk.W, stretch=True)

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        self.selection_info_label = ttk.Label(list_group, text="Načítám seznam...", font=("Segoe UI", 9, "bold"))
        self.selection_info_label.pack(fill=tk.X, pady=(4, 0))

        # 4. VOLBY A NASTAVENÍ
        opts_frame = ttk.Frame(main_frame)
        opts_frame.pack(fill=tk.X, pady=(0, 6))

        self.backup_var = tk.BooleanVar(value=self.config.get("create_backup", True))
        ttk.Checkbutton(opts_frame, text="Vytvořit zálohu před aktualizací (_backups/)",
                        variable=self.backup_var, command=self._save_settings).pack(side=tk.LEFT, padx=(0, 15))

        self.autokill_var = tk.BooleanVar(value=self.config.get("auto_kill_idos", True))
        ttk.Checkbutton(opts_frame, text="Automaticky ukončit TT.exe před instalací",
                        variable=self.autokill_var, command=self._save_settings).pack(side=tk.LEFT, padx=(0, 15))

        self.launch_after_var = tk.BooleanVar(value=self.config.get("launch_after_update", False))
        ttk.Checkbutton(opts_frame, text="Spustit IDOS po úspěšné aktualizaci",
                        variable=self.launch_after_var, command=self._save_settings).pack(side=tk.LEFT)

        # 5. PRŮBĚH AKTUALIZACE & TLAČÍTKO SPUŠTĚNÍ
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(4, 0))

        progress_container = ttk.Frame(bottom_frame)
        progress_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.progress_label = ttk.Label(progress_container, text="Připraven.", font=("Segoe UI", 8))
        self.progress_label.pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_container, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(2, 0))

        self.action_btn = tk.Button(
            bottom_frame,
            text="▶ AKTUALIZOVAT VYBRANÉ",
            bg="#007acc",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=8,
            relief=tk.RAISED,
            command=self.start_update
        )
        self.action_btn.pack(side=tk.RIGHT)

        # 6. PROTOKOL / LOGY
        log_group = ttk.LabelFrame(main_frame, text=" 📝 Záznam operací ", padding="4")
        log_group.pack(fill=tk.BOTH, expand=False, pady=(6, 0))
        log_group.configure(height=110)

        self.log_text = tk.Text(log_group, height=5, font=("Consolas", 8), bg="#f8f9fa", fg="#212529", wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_group, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def log(self, message: str):
        """Zapíše zprávu do záznamu operací."""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _browse_path(self):
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or r"C:\IDOS", title="Vyberte složku IDOS")
        if selected:
            self.path_var.set(os.path.normpath(selected))
            self._on_path_changed()

    def _autodetect_path(self):
        detected = IdosEnvironment.find_default_path()
        if detected:
            self.path_var.set(detected)
            self.log(f"Autodetekce: Nalezena složka IDOS v {detected}")
        else:
            self.log("Autodetekce: IDOS nebyl nalezen v běžných umístěních, nastaveno na C:\\IDOS")
            self.path_var.set(r"C:\IDOS")
        self._on_path_changed()

    def _on_path_changed(self):
        self._refresh_path_status()
        self._rescan_local_files()
        self._save_settings()
        self._filter_tree()

    def _rescan_local_files(self):
        path = self.path_var.get().strip()
        self.scan_result = IdosEnvironment.scan_local_files(path)

    def _refresh_path_status(self):
        path = self.path_var.get().strip()
        if not path:
            self.path_status_label.config(text="⚠️ Zadejte cestu ke složce IDOS", foreground="#cc0000")
            return

        if os.path.isdir(path):
            tt_exe = os.path.join(path, "TT.exe")
            if os.path.isfile(tt_exe):
                self.path_status_label.config(text="✓ Nalezena platná instalace IDOS (TT.exe existuje)", foreground="#008000")
            else:
                self.path_status_label.config(text="ℹ️ Složka existuje, TT.exe ještě není nainstalován", foreground="#d97706")
        else:
            self.path_status_label.config(text="ℹ️ Složka zatím neexistuje (bude vytvořena při aktualizaci)", foreground="#555555")

    def _check_process_status(self):
        try:
            is_running = IdosEnvironment.is_idos_running()
            if is_running:
                self.proc_status_label.config(text="🔴 IDOS právě běží", foreground="#cc0000")
                self.kill_proc_btn.pack(side=tk.LEFT)
            else:
                self.proc_status_label.config(text="🟢 IDOS neběží", foreground="#008000")
                self.kill_proc_btn.pack_forget()
        except Exception:
            pass

        self.after(3000, self._check_process_status)

    def _kill_idos(self):
        if IdosEnvironment.kill_idos():
            self.log("Proces IDOS (TT.exe) byl ukončen.")
            self._check_process_status()
        else:
            messagebox.showwarning("Upozornění", "Nepodařilo se ukončit proces IDOS.")

    def _launch_idos(self):
        path = self.path_var.get().strip()
        if IdosEnvironment.launch_idos(path):
            self.log(f"IDOS byl spuštěn z {path}")
        else:
            messagebox.showerror("Chyba", f"Nepodařilo se spustit IDOS. Soubor TT.exe v '{path}' neexistuje.")

    def _save_settings(self):
        self.config["idos_path"] = self.path_var.get().strip()
        self.config["create_backup"] = self.backup_var.get()
        self.config["auto_kill_idos"] = self.autokill_var.get()
        self.config["launch_after_update"] = self.launch_after_var.get()
        self.config_mgr.save_config(self.config)

    def refresh_updates_list(self):
        self.log("Připojuji se k serveru chaps.cz a stahuji aktuální seznam balíčků...")
        self.selection_info_label.config(text="Stahuji seznam balíčků z chaps.cz...")

        def worker():
            try:
                scraper = ChapsScraper()
                items = scraper.fetch_updates()
                self.after(0, lambda: self._on_updates_fetched(items))
            except Exception as e:
                self.after(0, lambda e=e: self._on_fetch_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_updates_fetched(self, items: List[UpdateItem]):
        self.items = items
        self.log(f"Úspěšně načteno {len(items)} balíčků z CHAPS.")

        self._rescan_local_files()

        categories = ["Všechny"] + sorted(list(set(it.category_label for it in items)))
        self.category_combo["values"] = categories
        if self.category_var.get() not in categories:
            self.category_var.set("Všechny")

        if not self.selected_filenames:
            outdated_count = sum(1 for it in self.items if IdosEnvironment.get_item_update_status(it, self.scan_result)[0] == "outdated")
            if outdated_count > 0:
                self._select_outdated_only()
            else:
                self._apply_preset("quick")
        else:
            self._filter_tree()

    def _on_fetch_error(self, err_msg: str):
        self.log(f"CHYBA při stahování seznamu: {err_msg}")
        self.selection_info_label.config(text="Nepodařilo se načíst balíčky ze serveru.")
        messagebox.showerror("Chyba spojení", f"Nepodařilo se načíst data z https://www.chaps.cz:\n\n{err_msg}")

    def _apply_preset(self, preset_key: str):
        if preset_key not in PRESETS:
            return
        preset = PRESETS[preset_key]
        self.selected_filenames.clear()
        for it in self.items:
            if preset["filter"](it):
                self.selected_filenames.add(it.filename)

        self.log(f"Aplikována předvolba: {preset['name']}")
        self._filter_tree()

    def _select_outdated_only(self):
        """Označí pouze balíčky, u kterých byla detekována novější verze na webu CHAPS."""
        self.selected_filenames.clear()
        outdated_count = 0
        for it in self.items:
            status_code, _, _ = IdosEnvironment.get_item_update_status(it, self.scan_result)
            if status_code == "outdated":
                self.selected_filenames.add(it.filename)
                outdated_count += 1

        self.log(f"Označeno {outdated_count} balíčků vyžadujících aktualizaci.")
        if outdated_count == 0:
            self.log("Všechny nainstalované balíčky jsou již aktuální.")
        self._filter_tree()

    def _select_not_installed(self):
        """Označí všechny balíčky, které nejsou nainstalovány (status not_installed)."""
        self.selected_filenames.clear()
        count = 0
        for it in self.items:
            status_code, _, _ = IdosEnvironment.get_item_update_status(it, self.scan_result)
            if status_code == "not_installed":
                self.selected_filenames.add(it.filename)
                count += 1
        self.log(f"Přidáno {count} nenainstalovaných balíčků do výběru.")
        self._filter_tree()

    def _clear_selection(self):
        self.selected_filenames.clear()
        self._filter_tree()

    def _select_all_visible(self):
        for child in self.tree.get_children():
            fn = self.tree.item(child, "values")[2]
            self.selected_filenames.add(fn)
        self._filter_tree()

    def _on_tree_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        self._toggle_tree_item(item_id)

    def _on_tree_space(self, event):
        selected = self.tree.selection()
        if selected:
            self._toggle_tree_item(selected[0])

    def _toggle_tree_item(self, item_id):
        values = list(self.tree.item(item_id, "values"))
        if not values:
            return
        filename = values[2]
        if filename in self.selected_filenames:
            self.selected_filenames.remove(filename)
            values[0] = " "
        else:
            self.selected_filenames.add(filename)
            values[0] = "✓"
        self.tree.item(item_id, values=values)
        self._update_selection_summary()

    def _filter_tree(self):
        query = self.search_var.get().strip().lower()
        cat_filter = self.category_var.get()
        status_filter = self.status_filter_var.get()

        for row in self.tree.get_children():
            self.tree.delete(row)

        visible_count = 0
        outdated_total = 0
        for it in self.items:
            status_code, status_label, _ = IdosEnvironment.get_item_update_status(it, self.scan_result)
            if status_code == "outdated":
                outdated_total += 1

            if status_filter == "🟠 Pouze vyžadující aktualizaci" and status_code != "outdated":
                continue
            elif status_filter == "🟢 Pouze aktuální" and status_code != "up_to_date":
                continue
            elif status_filter == "⚪ Pouze nenainstalované" and status_code != "not_installed":
                continue
            elif status_filter == "🟠+⚪ Zastaralé nebo chybějící" and status_code not in ("outdated", "not_installed"):
                continue

            if cat_filter != "Všechny" and it.category_label != cat_filter:
                continue

            if query:
                full_text = f"{it.filename} {it.title} {it.description} {it.category_label} {status_label}".lower()
                if query not in full_text:
                    continue

            is_sel = it.filename in self.selected_filenames
            sel_str = "✓" if is_sel else " "

            self.tree.insert("", tk.END, values=(
                sel_str,
                status_label,
                it.filename,
                it.category_label,
                it.date,
                it.size_str,
                it.description
            ))
            visible_count += 1

        self._update_selection_summary(outdated_total)

    def _update_selection_summary(self, outdated_total: Optional[int] = None):
        sel_items = [it for it in self.items if it.filename in self.selected_filenames]
        total_size = sum(it.size_bytes for it in sel_items)
        size_mb = total_size / (1024 * 1024)

        if outdated_total is None:
            outdated_total = sum(1 for it in self.items if IdosEnvironment.get_item_update_status(it, self.scan_result)[0] == "outdated")

        status_suffix = f"  |  🟠 K aktualizaci: {outdated_total}" if outdated_total > 0 else "  |  🟢 Vše nainstalované je aktuální"

        self.selection_info_label.config(
            text=f"Vybráno: {len(sel_items)} z {len(self.items)} balíčků  |  Velikost: {size_mb:.2f} MB{status_suffix}"
        )

    def start_update(self):
        if self.is_updating:
            return

        idos_path = self.path_var.get().strip()
        if not idos_path:
            messagebox.showwarning("Chybí cesta", "Prosím zadejte nebo vyberte složku instalace IDOS.")
            return

        # Include selected items and any packages that are not installed
        sel_items = [
            it for it in self.items
            if (it.filename in self.selected_filenames) or (
                IdosEnvironment.get_item_update_status(it, self.scan_result)[0] == "not_installed"
            )
        ]
        if not sel_items:
            messagebox.showinfo("Prázdný výběr", "Nevybrali jste žádné balíčky k aktualizaci.")
            return

        if IdosEnvironment.is_idos_running():
            if self.autokill_var.get():
                self.log("Ukončuji běžící proces TT.exe před instalací...")
                if not IdosEnvironment.kill_idos():
                    if not messagebox.askyesno("IDOS běží", "Nepodařilo se automaticky ukončit IDOS. Chcete přesto pokračovat?"):
                        return
            else:
                resp = messagebox.askyesno(
                    "IDOS běží",
                    "Program IDOS je spuštěn. Před aktualizací je nutné jej ukončit.\n\nChcete jej ukončit nyní?"
                )
                if resp:
                    IdosEnvironment.kill_idos()
                else:
                    return

        self.is_updating = True
        self.cancel_requested = False
        self.action_btn.config(text="⏳ Probíhá aktualizace...", state=tk.DISABLED, bg="#6c757d")
        self.progress_bar["value"] = 0
        self._save_settings()

        threading.Thread(target=self._update_worker, args=(idos_path, sel_items), daemon=True).start()

    def _update_worker(self, idos_path: str, items: List[UpdateItem]):
        self.log("\n" + "=" * 55)
        self.log(f"Začíná aktualizace {len(items)} balíčků...")
        self.log(f"Cílová složka: {idos_path}")

        # 1. Zálohování
        if self.backup_var.get() and os.path.isdir(idos_path) and os.listdir(idos_path):
            self.after(0, lambda: self.progress_label.config(text="Vytvářím zálohu stávajících dat..."))
            BackupManager.create_backup(idos_path, log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))

        # 2. Stahování a instalace
        updater = UpdateManager(idos_path)
        total_items = len(items)

        def progress_cb(item, dl_bytes, total_bytes, ratio, speed_str):
            idx = items.index(item) + 1
            overall_ratio = ((idx - 1) + ratio) / total_items
            pct = int(overall_ratio * 100)

            def update_ui():
                self.progress_bar["value"] = pct
                self.progress_label.config(
                    text=f"[{idx}/{total_items}] {item.filename} - {speed_str} ({int(ratio*100)}%)"
                )
            self.after(0, update_ui)

        def log_cb(msg):
            self.after(0, lambda m=msg: self.log(m))

        def cancel_check():
            return self.cancel_requested

        success_cnt, err_cnt, errors = updater.download_and_extract(
            items=items,
            progress_callback=progress_cb,
            log_callback=log_cb,
            cancel_check=cancel_check
        )

        def on_complete():
            self.is_updating = False
            self.action_btn.config(text="▶ AKTUALIZOVAT VYBRANÉ", state=tk.NORMAL, bg="#007acc")
            self.progress_bar["value"] = 100
            self.progress_label.config(text="Aktualizace dokončena.")
            self._refresh_path_status()
            self._rescan_local_files()
            self._filter_tree()

            self.log("=" * 55)
            if err_cnt == 0:
                self.log(f"✓ ÚSPĚŠNĚ DOKONČENO: Nainstalováno {success_cnt} balíčků.")
                messagebox.showinfo("Hotovo", f"Aktualizace proběhla úspěšně!\n\nNainstalováno: {success_cnt} balíčků.")
            else:
                self.log(f"⚠️ DOKONČENO S CHYBAMI: {success_cnt} úspěšných, {err_cnt} chyb.")
                err_detail_text = "\n\n".join(errors)
                self.log(f"Detail chyb:\n{err_detail_text}")
                messagebox.showerror(
                    "Chyby při aktualizaci",
                    f"Při aktualizaci došlo k {err_cnt} chybám:\n\n{err_detail_text}\n\nZkontrolujte protokol v okně aplikace."
                )

            if self.launch_after_var.get() and err_cnt == 0:
                self._launch_idos()

        self.after(0, on_complete)


def run_gui():
    app = IdosUpdaterGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
