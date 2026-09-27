# 🚆 IDOS Updater (CHAPS)

Kompletná a spoľahlivá aplikácia v Pythone na automatickú aktualizáciu programu a cestovných poriadkov offline aplikácie **IDOS pre Windows** od spoločnosti **CHAPS spol. s r.o.** (zdroj: [chaps.cz/cs/download/idos](https://www.chaps.cz/cs/download/idos)).

---

## ✨ Kľúčové vlastnosti

- **🖥️ Moderné grafické rozhranie (GUI):**
  - Prehľadná tabuľka všetkých 220+ balíčkov rozdelených podľa kategórií (Program, Vlaky, Autobusy, MHD mestá, Tarify, Mapy, Doplnkové info).
  - Rýchle filtrovanie a fulltextové vyhľadávanie (napr. *Brno*, *PID*, *Košice*, *Vlaky*).
  - Predvolené rýchle sady (Presety):
    - ⚡ **Rýchla aktualizácia** (Program + TT Font + Vlaky ČR/Európa + Autobusy ČR/SR)
    - 📦 **Kompletná aktualizácia** (Program + archív `KOMPLET.ZIP`)
    - 🚆 **Iba Vlaky a Autobusy**
    - ⚙️ **Iba samotný program** (`TTAKT.ZIP` + `TTFONT.ZIP`)
  - Sledovanie rýchlosti sťahovania, ETA, veľkosti a percentuálneho priebehu v reálnom čase.
  - Tlačidlo **▶ Spustiť IDOS** priamo z aplikácie.

- **⚙️ Konzolový režim (CLI) pre automatizáciu a Plánovač úloh:**
  - Podpora pre bezobslužný beh (`--non-interactive`, `--preset quick`, `--launch`, atď.).
  - Možnosť integrovať do cronu alebo Windows Task Scheduler na pravidelnú aktualizáciu napr. každý piatok.

- **🛡️ Bezpečnosť a spoľahlivosť:**
  - **Detekcia a zatvorenie bežiaceho IDOS**: Skontroluje, či beží `TT.exe`, aby nedošlo k uzamknutiu súborov pri prepise.
  - **Automatické zálohovanie**: Pred prepísaním vytvorí timestamped ZIP archív v priečinku `_backups/`.
  - **Správne rozbalenie `TTAKT.ZIP`**: Automaticky ošetrí špecifikum CHAPS archívu (presunie súbory z vnútorného priečinka `App/` priamo do koreňa IDOS).
  - **Žiadne externé závislosti**: Funguje ihneď na čistom Pythone 3.8+ bez potreby inštalovať ďalšie pip balíčky.

---

## 🚀 Spustenie aplikácie

### 1. Spustenie Grafického rozhrania (GUI)

Stačí dvakrát kliknúť na **`run_gui.bat`** alebo spustiť cez terminál:

```bash
python main.py
```

### 2. Spustenie cez príkazový riadok (CLI)

#### Zoznam a vyhľadávanie:
```bash
# Zoznam všetkých dostupných balíčkov z CHAPS
python main.py --list

# Vyhľadanie konkrétneho mesta / linky
python main.py --search "Brno"
python main.py --search "Praha"
```

#### Rýchla aktualizácia:
```bash
# Aktualizácia cez preset (rýchly balík: program + vlaky + busy) a následné spustenie IDOS
python main.py --preset quick --launch

# Kompletná aktualizácia
python main.py --preset komplet --path "C:\IDOS"

# Bezobslužná aktualizácia pre Windows Plánovač úloh (Task Scheduler)
python main.py --preset quick --non-interactive --yes --kill-running
```

#### Výber konkrétnych súborov:
```bash
python main.py --files TTAKT.ZIP VLAK26E.ZIP IDSJMK.ZIP --path "C:\IDOS"
```

---

## 📂 Štruktúra projektu

```
idos_updater/
│
├── idos_updater/
│   ├── __init__.py      # Verzia balíka a metadáta
│   ├── __main__.py      # Štartovací bod balíka
│   ├── core.py          # Logika sťahovania, parsovania CHAPS, extrakcie, zálohovania
│   ├── cli.py           # Plnohodnotné CLI rozhranie s argumentmi
│   └── gui.py           # Moderné okenné Tkinter rozhranie
│
├── main.py              # Hlavný spúšťač (GUI alebo CLI podľa argumentov)
├── run_gui.bat          # Dvojklikový spúšťač GUI pre Windows
├── update_quick.bat     # Dvojklikový spúšťač rýchlej aktualizácie
├── requirements.txt     # Informácie o závislostiach
└── README.md            # Dokumentácia a návod
```

---

## 📋 Dostupné presety

| Kód presetu | Názov | Zahrnuté súbory |
| :--- | :--- | :--- |
| `quick` | ⚡ Rýchla aktualizácia | `TTAKT.ZIP`, `TTFONT.ZIP`, `VLAK26E.ZIP`, `VLAK26C.ZIP`, `BUS26C.ZIP`, `BUS26S.ZIP` |
| `komplet` | 📦 Kompletná | `TTAKT.ZIP`, `TTFONT.ZIP`, `KOMPLET.ZIP` |
| `trains_buses` | 🚆 Vlaky & Autobusy | `VLAK26E.ZIP`, `VLAK26C.ZIP`, `VLAKPID26.ZIP`, `BUS26C.ZIP`, `BUS26CK.ZIP`, `BUS26CKD.ZIP`, `BUS26S.ZIP` |
| `program_only`| ⚙️ Iba Program | `TTAKT.ZIP`, `TTFONT.ZIP` |
| `all_individual` | 🌐 Všetko jednotlivo | Všetkých 200+ balíčkov vrátane všetkých MHD |

---

## ⚖️ Licenčné upozornenie

Data cestovných poriadkov sú autorským dielom spoločnosti **CHAPS spol. s r.o.** a sú určené pre držiteľov príslušných licencií k softvéru IDOS.
