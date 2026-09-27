"""
Grafické rozhranie (GUI) pre IDOS Updater v knižnici Tkinter.
Umožňuje pohodlný výber balíčkov, predvolené sady (presety), vyhľadávanie,
automatickú detekciu inštalácie, zálohovanie a sledovanie priebehu sťahovania v reálnom čase.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Dict, Set, Optional

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
        self.geometry("980, 720")
        self.minsize(800, 600)

        # Načítanie konfigurácie
        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.load_config()

        # Stavové premenné
        self.items: List[UpdateItem] = []
        self.selected_filenames: Set[str] = set()
        self.is_updating = False
        self.cancel_requested = False

        # Nastavenie štýlu
        self._setup_styles()

        # Vytvorenie používateľského rozhrania
        self._create_widgets()

        # Inicializácia ciest a kontrola
        self._refresh_path_status()
        self._check_process_status()

        # Asynchrónne načítanie zoznamu aktualizácií z webu
        self.after(100, self.refresh_updates_list)

    def _setup_styles(self):
        self.style = ttk.Style(self)
        # Výber motívu
        available_themes = self.style.theme_names()
        if 'clam' in available_themes:
            self.style.theme_use('clam')
        elif 'vista' in available_themes:
            self.style.theme_use('vista')

        # Vlastné farby a písma
        self.style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=6)
        self.style.configure("Preset.TButton", font=("Segoe UI", 9), padding=4)
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9, "bold"))

    def _create_widgets(self):
        # Hlavný kontajner
        main_frame = ttk.Frame(self, padding="10 10 10 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. HLAVIČKA A CESTA K IDOS
        path_group = ttk.LabelFrame(main_frame, text=" 📁 Inštalácia IDOS ", padding="8")
        path_group.pack(fill=tk.X, pady=(0, 8))

        path_top_row = ttk.Frame(path_group)
        path_top_row.pack(fill=tk.X)

        ttk.Label(path_top_row, text="Priečinok IDOS:").pack(side=tk.LEFT, padx=(0, 6))
        self.path_var = tk.StringVar(value=self.config.get("idos_path", r"C:\IDOS"))
        self.path_entry = ttk.Entry(path_top_row, textvariable=self.path_var, width=50)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.path_entry.bind("<KeyRelease>", lambda e: self._refresh_path_status())

        ttk.Button(path_top_row, text="Prehľadávať...", command=self._browse_path).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(path_top_row, text="Autodetekcia", command=self._autodetect_path).pack(side=tk.LEFT, padx=(0, 4))
        self.launch_btn = ttk.Button(path_top_row, text="▶ Spustiť IDOS", command=self._launch_idos)
        self.launch_btn.pack(side=tk.LEFT, padx=(4, 0))

        # Stavový riadok inštalácie a bežiaceho procesu
        path_status_row = ttk.Frame(path_group)
        path_status_row.pack(fill=tk.X, pady=(6, 0))

        self.path_status_label = ttk.Label(path_status_row, text="Kontrola priečinka...", font=("Segoe UI", 8))
        self.path_status_label.pack(side=tk.LEFT)

        self.proc_status_frame = ttk.Frame(path_status_row)
        self.proc_status_frame.pack(side=tk.RIGHT)
        self.proc_status_label = ttk.Label(self.proc_status_frame, text="", font=("Segoe UI", 8, "bold"))
        self.proc_status_label.pack(side=tk.LEFT, padx=(0, 6))
        self.kill_proc_btn = ttk.Button(self.proc_status_frame, text="Ukončiť IDOS", command=self._kill_idos, width=12)

        # 2. RÝCHLE PRESETY (TLAČIDLÁ)
        preset_group = ttk.LabelFrame(main_frame, text=" ⚡ Rýchly výber (Predvoľby) ", padding="6")
        preset_group.pack(fill=tk.X, pady=(0, 8))

        preset_btn_frame = ttk.Frame(preset_group)
        preset_btn_frame.pack(fill=tk.X)

        ttk.Button(preset_btn_frame, text="⚡ Rýchla (Program + Vlaky + Busy)", style="Preset.TButton",
                   command=lambda: self._apply_preset("quick")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="📦 Kompletná (KOMPLET + Program)", style="Preset.TButton",
                   command=lambda: self._apply_preset("komplet")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="🚆 Iba Vlaky & Busy", style="Preset.TButton",
                   command=lambda: self._apply_preset("trains_buses")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="⚙️ Iba Program", style="Preset.TButton",
                   command=lambda: self._apply_preset("program_only")).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_btn_frame, text="🧹 Zrušiť výber", style="Preset.TButton",
                   command=self._clear_selection).pack(side=tk.RIGHT, padx=2)

        # 3. VYHĽADÁVANIE A ZOZNAM BALÍČKOV
        list_group = ttk.LabelFrame(main_frame, text=" 📦 Dostupné balíčky z CHAPS ", padding="6")
        list_group.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Filter row
        filter_row = ttk.Frame(list_group)
        filter_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(filter_row, text="🔍 Filter / Hľadať:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_row, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_tree())

        ttk.Label(filter_row, text="Kategória:").pack(side=tk.LEFT, padx=(8, 4))
        self.category_var = tk.StringVar(value="Všetky")
        self.category_combo = ttk.Combobox(filter_row, textvariable=self.category_var, state="readonly", width=25)
        self.category_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_tree())

        ttk.Button(filter_row, text="🔄 Obnoviť z webu", command=self.refresh_updates_list).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(filter_row, text="Označiť zobrazené", command=self._select_all_visible).pack(side=tk.RIGHT, padx=(4, 0))

        # Tabuľka / Treeview
        tree_frame = ttk.Frame(list_group)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("selected", "filename", "category", "date", "size", "description")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("selected", text="✓", anchor=tk.CENTER)
        self.tree.heading("filename", text="Súbor", anchor=tk.W)
        self.tree.heading("category", text="Kategória", anchor=tk.W)
        self.tree.heading("date", text="Dátum", anchor=tk.CENTER)
        self.tree.heading("size", text="Veľkosť", anchor=tk.E)
        self.tree.heading("description", text="Popis / Obsah", anchor=tk.W)

        self.tree.column("selected", width=40, anchor=tk.CENTER, stretch=False)
        self.tree.column("filename", width=120, anchor=tk.W, stretch=False)
        self.tree.column("category", width=190, anchor=tk.W, stretch=False)
        self.tree.column("date", width=95, anchor=tk.CENTER, stretch=False)
        self.tree.column("size", width=105, anchor=tk.E, stretch=False)
        self.tree.column("description", width=350, anchor=tk.W, stretch=True)

        # Scrollbary
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Kliknutie na riadok prepína označenie
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        # Info panel pod tabuľkou
        self.selection_info_label = ttk.Label(list_group, text="Načítavam zoznam...", font=("Segoe UI", 9, "bold"))
        self.selection_info_label.pack(fill=tk.X, pady=(4, 0))

        # 4. MOŽNOSTI A NASTAVENIA
        opts_frame = ttk.Frame(main_frame)
        opts_frame.pack(fill=tk.X, pady=(0, 6))

        self.backup_var = tk.BooleanVar(value=self.config.get("create_backup", True))
        ttk.Checkbutton(opts_frame, text="Vytvoriť zálohu pred aktualizáciou (_backups/)",
                        variable=self.backup_var, command=self._save_settings).pack(side=tk.LEFT, padx=(0, 15))

        self.autokill_var = tk.BooleanVar(value=self.config.get("auto_kill_idos", True))
        ttk.Checkbutton(opts_frame, text="Automaticky ukončiť TT.exe pred inštaláciou",
                        variable=self.autokill_var, command=self._save_settings).pack(side=tk.LEFT, padx=(0, 15))

        self.launch_after_var = tk.BooleanVar(value=self.config.get("launch_after_update", False))
        ttk.Checkbutton(opts_frame, text="Spustiť IDOS po úspešnej aktualizácii",
                        variable=self.launch_after_var, command=self._save_settings).pack(side=tk.LEFT)

        # 5. PRIEBEH AKTUALIZÁCIE & TLAČIDLO SPUSTENIA
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(4, 0))

        progress_container = ttk.Frame(bottom_frame)
        progress_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.progress_label = ttk.Label(progress_container, text="Pripravený.", font=("Segoe UI", 8))
        self.progress_label.pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_container, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(2, 0))

        self.action_btn = tk.Button(
            bottom_frame,
            text="▶ AKTUALIZOVAŤ VYBRANÉ",
            bg="#007acc",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=8,
            relief=tk.RAISED,
            command=self.start_update
        )
        self.action_btn.pack(side=tk.RIGHT)

        # 6. PROTOKOL / LOGY (Rozbaliteľný)
        log_group = ttk.LabelFrame(main_frame, text=" 📝 Záznam operácií ", padding="4")
        log_group.pack(fill=tk.BOTH, expand=False, pady=(6, 0))
        log_group.configure(height=100)

        self.log_text = tk.Text(log_group, height=4, font=("Consolas", 8), bg="#f8f9fa", fg="#212529", wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_group, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def log(self, message: str):
        """Zapíše správu do záznamu operácií."""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _browse_path(self):
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or r"C:\IDOS", title="Vyberte priečinok IDOS")
        if selected:
            self.path_var.set(os.path.normpath(selected))
            self._refresh_path_status()
            self._save_settings()

    def _autodetect_path(self):
        detected = IdosEnvironment.find_default_path()
        if detected:
            self.path_var.set(detected)
            self.log(f"Autodetekcia: Nájdený priečinok IDOS v {detected}")
        else:
            self.log("Autodetekcia: IDOS sa nenašiel v bežných umiestneniach, nastavené na C:\\IDOS")
            self.path_var.set(r"C:\IDOS")
        self._refresh_path_status()
        self._save_settings()

    def _refresh_path_status(self):
        path = self.path_var.get().strip()
        if not path:
            self.path_status_label.config(text="⚠️ Zadajte cestu k priečinku IDOS", foreground="#cc0000")
            return

        if os.path.isdir(path):
            tt_exe = os.path.join(path, "TT.exe")
            if os.path.isfile(tt_exe):
                self.path_status_label.config(text="✓ Nájdená platná inštalácia IDOS (TT.exe existuje)", foreground="#008000")
            else:
                self.path_status_label.config(text="ℹ️ Priečinok existuje, TT.exe ešte nie je nainštalovaný", foreground="#d97706")
        else:
            self.path_status_label.config(text="ℹ️ Priečinok zatiaľ neexistuje (bude vytvorený pri aktualizácii)", foreground="#555555")

    def _check_process_status(self):
        """Pravidelná kontrola, či beží IDOS."""
        try:
            is_running = IdosEnvironment.is_idos_running()
            if is_running:
                self.proc_status_label.config(text="🔴 IDOS práve beží", foreground="#cc0000")
                self.kill_proc_btn.pack(side=tk.LEFT)
            else:
                self.proc_status_label.config(text="🟢 IDOS nebeží", foreground="#008000")
                self.kill_proc_btn.pack_forget()
        except Exception:
            pass

        # Naplánovať ďalšiu kontrolu o 3 sekundy
        self.after(3000, self._check_process_status)

    def _kill_idos(self):
        if IdosEnvironment.kill_idos():
            self.log("Proces IDOS (TT.exe) bol ukončený.")
            self._check_process_status()
        else:
            messagebox.showwarning("Upozornenie", "Nepodarilo sa ukončiť proces IDOS.")

    def _launch_idos(self):
        path = self.path_var.get().strip()
        if IdosEnvironment.launch_idos(path):
            self.log(f"IDOS bol spustený z {path}")
        else:
            messagebox.showerror("Chyba", f"Nepodarilo sa spustiť IDOS. Súbor TT.exe v '{path}' neexistuje.")

    def _save_settings(self):
        self.config["idos_path"] = self.path_var.get().strip()
        self.config["create_backup"] = self.backup_var.get()
        self.config["auto_kill_idos"] = self.autokill_var.get()
        self.config["launch_after_update"] = self.launch_after_var.get()
        self.config_mgr.save_config(self.config)

    def refresh_updates_list(self):
        """Asynchrónne stiahne zoznam aktualizácií z webu CHAPS."""
        self.log("Pripájam sa k serveru chaps.cz a sťahujem aktuálny zoznam balíčkov...")
        self.selection_info_label.config(text="Sťahujem zoznam balíčkov z chaps.cz...")

        def worker():
            try:
                scraper = ChapsScraper()
                items = scraper.fetch_updates()
                self.after(0, lambda: self._on_updates_fetched(items))
            except Exception as e:
                self.after(0, lambda: self._on_fetch_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_updates_fetched(self, items: List[UpdateItem]):
        self.items = items
        self.log(f"Úspešne načítaných {len(items)} balíčkov z CHAPS.")

        # Aktualizácia kategórií v Comboboxe
        categories = ["Všetky"] + sorted(list(set(it.category_label for it in items)))
        self.category_combo["values"] = categories
        if self.category_var.get() not in categories:
            self.category_var.set("Všetky")

        # Predvolene aplikujeme 'quick' preset ak ešte nie je nič zvolené
        if not self.selected_filenames:
            self._apply_preset("quick")
        else:
            self._filter_tree()

    def _on_fetch_error(self, err_msg: str):
        self.log(f"CHYBA pri sťahovaní zoznamu: {err_msg}")
        self.selection_info_label.config(text="Nepodarilo sa načítať balíčky zo servera.")
        messagebox.showerror("Chyba spojenia", f"Nepodarilo sa načítať dáta z https://www.chaps.cz:\n\n{err_msg}")

    def _apply_preset(self, preset_key: str):
        if preset_key not in PRESETS:
            return
        preset = PRESETS[preset_key]
        self.selected_filenames.clear()
        for it in self.items:
            if preset["filter"](it):
                self.selected_filenames.add(it.filename)

        self.log(f"Aplikovaná predvoľba: {preset['name']}")
        self._filter_tree()

    def _clear_selection(self):
        self.selected_filenames.clear()
        self._filter_tree()

    def _select_all_visible(self):
        for child in self.tree.get_children():
            fn = self.tree.item(child, "values")[1]
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
        filename = values[1]
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

        # Vyčistiť tabuľku
        for row in self.tree.get_children():
            self.tree.delete(row)

        visible_count = 0
        for it in self.items:
            # Filter podľa kategórie
            if cat_filter != "Všetky" and it.category_label != cat_filter:
                continue

            # Filter podľa hľadaného textu
            if query:
                full_text = f"{it.filename} {it.title} {it.description} {it.category_label}".lower()
                if query not in full_text:
                    continue

            is_sel = it.filename in self.selected_filenames
            sel_str = "✓" if is_sel else " "

            self.tree.insert("", tk.END, values=(
                sel_str,
                it.filename,
                it.category_label,
                it.date,
                it.size_str,
                it.description
            ))
            visible_count += 1

        self._update_selection_summary()

    def _update_selection_summary(self):
        sel_items = [it for it in self.items if it.filename in self.selected_filenames]
        total_size = sum(it.size_bytes for it in sel_items)
        size_mb = total_size / (1024 * 1024)

        self.selection_info_label.config(
            text=f"Vybraných: {len(sel_items)} z {len(self.items)} balíčkov  |  Celková veľkosť: {size_mb:.2f} MB"
        )

    def start_update(self):
        """Spustí proces sťahovania a inštalácie vo vedľajšom vlákne."""
        if self.is_updating:
            return

        idos_path = self.path_var.get().strip()
        if not idos_path:
            messagebox.showwarning("Chýba cesta", "Prosím zadajte alebo vyberte priečinok inštalácie IDOS.")
            return

        sel_items = [it for it in self.items if it.filename in self.selected_filenames]
        if not sel_items:
            messagebox.showinfo("Prázdny výber", "Nevybrali ste žiadne balíčky na aktualizáciu.")
            return

        # Kontrola bežiaceho procesu IDOS
        if IdosEnvironment.is_idos_running():
            if self.autokill_var.get():
                self.log("Ukončujem bežiaci proces TT.exe pred inštaláciou...")
                if not IdosEnvironment.kill_idos():
                    if not messagebox.askyesno("IDOS beží", "Nepodarilo sa automaticky ukončiť IDOS. Chcete pokračovať napriek tomu?"):
                        return
            else:
                resp = messagebox.askyesno(
                    "IDOS beží",
                    "Program IDOS je spustený. Pred aktualizáciou je nutné ho ukončiť.\n\nChcete ho ukončiť teraz?"
                )
                if resp:
                    IdosEnvironment.kill_idos()
                else:
                    return

        # Nastavenie stavu na bežiaci
        self.is_updating = True
        self.cancel_requested = False
        self.action_btn.config(text="⏳ Prebieha aktualizácia...", state=tk.DISABLED, bg="#6c757d")
        self.progress_bar["value"] = 0
        self._save_settings()

        # Spustenie pracovného vlákna
        threading.Thread(target=self._update_worker, args=(idos_path, sel_items), daemon=True).start()

    def _update_worker(self, idos_path: str, items: List[UpdateItem]):
        self.log("\n" + "=" * 55)
        self.log(f"Začína aktualizácia {len(items)} balíčkov...")
        self.log(f"Cieľový priečinok: {idos_path}")

        # 1. Zálohovanie
        if self.backup_var.get() and os.path.isdir(idos_path) and os.listdir(idos_path):
            self.after(0, lambda: self.progress_label.config(text="Vytváram zálohu existujúcich dát..."))
            BackupManager.create_backup(idos_path, log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))

        # 2. Sťahovanie a inštalácia
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
            self.action_btn.config(text="▶ AKTUALIZOVAŤ VYBRANÉ", state=tk.NORMAL, bg="#007acc")
            self.progress_bar["value"] = 100
            self.progress_label.config(text="Aktualizácia úspešne dokončená.")
            self._refresh_path_status()

            self.log("=" * 55)
            if err_cnt == 0:
                self.log(f"✓ ÚSPEŠNE DOKONČENÉ: Nainštalovaných {success_cnt} balíčkov.")
                messagebox.showinfo("Hotovo", f"Aktualizácia prebehla úspešne!\n\nNainštalovaných: {success_cnt} balíčkov.")
            else:
                self.log(f"⚠️ DOKONČENÉ S CHYBAMI: {success_cnt} úspešných, {err_cnt} chýb.")
                messagebox.showwarning("Dokončené s chybami", f"Aktualizácia skončila s chybami ({err_cnt} chýb).\nPozrite si záznam operácií.")

            # Spustenie IDOS po aktualizácii
            if self.launch_after_var.get() and err_cnt == 0:
                self._launch_idos()

        self.after(0, on_complete)


def run_gui():
    app = IdosUpdaterGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
