# 🚆 IDOS Updater (CHAPS)

Kompletní a spolehlivá aplikace v Pythonu pro automatickou aktualizaci programu a jízdních řádů offline aplikace **IDOS pro Windows** od společnosti **CHAPS spol. s r.o.** (zdroj: [chaps.cz/cs/download/idos](https://www.chaps.cz/cs/download/idos)).

---

## ✨ Klíčové vlastnosti

- **🖥️ Moderní grafické rozhraní (GUI):**
  - Přehledná tabulka všech 220+ balíčků rozdělených podle kategorií (Programové vybavení, Jízdní řády - Vlaky, Autobusy, MHD města, Tarifní soubory, Mapy, Doplňkové info).
  - Rychlé filtrování a fulltextové vyhledávání (např. *Brno*, *PID*, *Ostrava*, *Vlaky*).
  - Přednastavené rychlé sady (Presety):
    - ⚡ **Označit vyžadující aktualizaci** – automaticky vybere pouze balíčky s novou verzí na webu CHAPS
    - ⚪ **Označit nenainstalované** – vybere všechny balíčky, které v cílové složce dosud chybí
    - ⚡ **Rychlá aktualizace** (Program `TTAKT` + písmo `TTFONT` + Vlaky ČR/Evropa + Autobusy ČR/SR)
    - 📦 **Kompletní aktualizace** (Program + archiv `KOMPLET.ZIP`)
    - 🚆 **Pouze Vlaky a Autobusy**
    - ⚙️ **Pouze samotný program** (`TTAKT.ZIP` + `TTFONT.ZIP`)
  - Sledování rychlosti stahování, přenesené velikosti a procentuálního průběhu v reálném čase.
  - Tlačítko **▶ Spustit IDOS** přímo z aplikace.

- **🌐 Lokální webové rozhraní:**
  - Spuštění v prohlížeči jako alternativa k desktopovému GUI.
  - Filtrování balíčků, jejich stavů a kategorií, výběr presetů a aktualizace s průběhem a protokolem.
  - Frontend používá React, Tailwind CSS a shadcn/ui; Python server naslouchá výhradně na tomto počítači (`127.0.0.1`).
  - Při běžném spuštění nejsou potřeba Node.js ani externí Python balíčky; Node.js je nutný pouze pro vývoj a sestavení frontendu.

- **⚙️ Konzolový režim (CLI) pro automatizaci a Plánovač úloh:**
  - Podpora pro bezobslužný běh (`--non-interactive`, `--preset quick`, `--launch`, atd.).
  - Možnost snadné integrace do Plánovače úloh systému Windows (Task Scheduler) pro pravidelné týdenní aktualizace.

- **🛡️ Bezpečnost a spolehlivost:**
  - **Detekce a ukončení běžícího IDOS**: Zkontroluje, zda běží proces `TT.exe`, aby nedošlo k uzamčení souborů při přepisu.
  - **Automatické zálohování**: Před přepsáním vytvoří timestamped ZIP archiv ve složce `_backups/`.
  - **Správné rozbalení `TTAKT.ZIP`**: Automaticky ošetří specifikum archivu CHAPS (přesune soubory z vnitřní složky `App/` přímo do kořene IDOS).
  - **Žádné externí závislosti**: Funguje ihned na čistém Pythonu 3.8+ bez nutnosti instalovat další balíčky přes pip.

---

## 🚀 Spuštění aplikace

### 1. Spuštění Grafického rozhraní (GUI)

Stačí dvakrát kliknout na **`run_gui.bat`** nebo spustit přes terminál:

```bash
python main.py
```

### 2. Spuštění webového rozhraní

Spusťte **`run_web.bat`** nebo z terminálu:

```bash
python main.py --web
```

Pro výběr jiné cílové složky lze použít `python main.py --web --path "C:\IDOS"`.
Webový server zůstává spuštěný v konzoli; ukončíte jej pomocí `Ctrl+C`.

### Sestavení webového frontendu

Hotové frontendové soubory jsou součástí repozitáře, takže pro běžné spuštění webového rozhraní není potřeba Node.js. Pro změny ve frontendu je potřeba Node.js 20.19 nebo novější:

```bash
cd web_client
npm ci
npm run dev
```

Otevřete `http://localhost:5173`. Vývojový server očekává běžící Python backend na `127.0.0.1:8765`; spusťte ho v druhém terminálu:

```bash
# PowerShell
$env:IDOS_WEB_PORT = "8765"
python ..\main.py --web
```

Před publikováním změn vytvořte distribuční frontendové soubory:

```bash
npm run build
```

Build se ukládá do `idos_updater/web_dist/` a tato složka se commituje spolu se zdrojovými změnami.

### 3. Spuštění přes příkazovou řádku (CLI)

#### Výpis a vyhledávání:
```bash
# Seznam všech dostupných balíčků z CHAPS
python main.py --list

# Vyhledání konkrétního města / linky
python main.py --search "Brno"
python main.py --search "Praha"
```

#### Rychlá aktualizace:
```bash
# Aktualizace přes preset (rychlý balík: program + vlaky + busy) a následné spuštění IDOS
python main.py --preset quick --launch

# Kompletní aktualizace do zadané složky
python main.py --preset komplet --path "C:\IDOS"

# Bezobslužná aktualizace pro Plánovač úloh (Task Scheduler)
python main.py --preset quick --non-interactive --yes --kill-running
```

#### Výběr konkrétních souborů:
```bash
python main.py --files TTAKT.ZIP VLAK26E.ZIP IDSJMK.ZIP --path "C:\IDOS"
```

---

## 📂 Struktura projektu

```
idos-updater/
│
├── idos_updater/
│   ├── __init__.py      # Verze balíčku a metadata
│   ├── __main__.py      # Spouštěcí bod balíčku
│   ├── core.py          # Logika stahování, parsování CHAPS, extrakce, zálohování
│   ├── cli.py           # Plnohodnotné CLI rozhraní s argumenty
│   ├── gui.py           # Grafické okenní rozhraní v Tkinter
│   ├── web.py           # Lokální HTTP server a aktualizace
│   └── web_dist/        # Sestavený webový frontend
│
├── main.py              # Hlavní spouštěč (GUI nebo CLI dle argumentů)
├── run_gui.bat          # Spouštěč GUI pro Windows (dvojklik)
├── run_web.bat          # Spouštěč webového rozhraní pro Windows
├── web_client/          # Zdrojové soubory React + Vite + Tailwind + shadcn/ui
├── update_quick.bat     # Spouštěč rychlé aktualizace pro Windows (dvojklik)
├── test_updater.py      # Integrační a unit testy
├── requirements.txt     # Informace o závislostech
└── README.md            # Dokumentace a návod
```

---

## 📋 Dostupné presety

| Kód presetu | Název | Zahrnuté soubory |
| :--- | :--- | :--- |
| `quick` | ⚡ Rychlá aktualizace | `TTAKT.ZIP`, `TTFONT.ZIP`, `VLAK26E.ZIP`, `VLAK26C.ZIP`, `BUS26C.ZIP`, `BUS26S.ZIP` |
| `komplet` | 📦 Kompletní | `TTAKT.ZIP`, `TTFONT.ZIP`, `KOMPLET.ZIP` |
| `trains_buses` | 🚆 Vlaky & Autobusy | `VLAK26E.ZIP`, `VLAK26C.ZIP`, `VLAKPID26.ZIP`, `BUS26C.ZIP`, `BUS26CK.ZIP`, `BUS26CKD.ZIP`, `BUS26S.ZIP` |
| `program_only`| ⚙️ Pouze Program | `TTAKT.ZIP`, `TTFONT.ZIP` |
| `all_individual` | 🌐 Vše jednotlivě | Všech 220+ balíčků včetně všech MHD měst |

---

## ⚖️ Licenční upozornění

Data jízdních řádů jsou autorským dílem společnosti **CHAPS spol. s r.o.** a jsou určena pro držitele příslušných licencí k softwaru IDOS.
