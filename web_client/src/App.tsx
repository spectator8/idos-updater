import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircle,
  ArrowDown,
  ArrowDownToLine,
  ArrowUp,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Clock3,
  FolderOpen,
  HardDrive,
  LoaderCircle,
  Play,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  TrainFront,
  X,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

type PackageStatus = "outdated" | "up_to_date" | "not_installed"
type SortColumn = "package" | "category" | "status" | "date" | "size"
type RequestAction =
  | "outdated"
  | "not_installed"
  | "quick"
  | "komplet"
  | "trains_buses"
  | "program_only"
  | "all_individual"
  | "all"
  | "clear"

interface PackageItem {
  filename: string
  title: string
  description: string
  category: string
  date: string
  size: string
  size_bytes: number
  status: PackageStatus
  status_label: string
  local_date: string | null
  selected: boolean
}

interface AppState {
  path: string
  create_backup: boolean
  auto_kill_idos: boolean
  launch_after_update: boolean
  refresh_state: "idle" | "loading" | "ready" | "error"
  refresh_error: string
  update_state: "idle" | "running" | "done" | "cancelled" | "error"
  update_error: string
  update_summary: string
  progress: {
    filename: string
    item_index: number
    item_count: number
    downloaded: number
    total: number
    ratio: number
    overall_ratio: number
    speed: string
  }
  items: PackageItem[]
  logs: string[]
  idos_running: boolean
}

interface ApiResponse extends Partial<AppState> {
  ok?: boolean
  error?: string
  message?: string
  state?: AppState
  csrf_token?: string
}

interface SortState {
  column: SortColumn
  direction: "asc" | "desc"
}

const actionLabels: { action: RequestAction; label: string }[] = [
  { action: "outdated", label: "Zastaralé" },
  { action: "not_installed", label: "Nenainstalované" },
  { action: "quick", label: "Rychlá sada" },
  { action: "komplet", label: "Kompletní" },
  { action: "trains_buses", label: "Vlaky a autobusy" },
  { action: "program_only", label: "Pouze program" },
  { action: "all_individual", label: "Vše jednotlivě" },
]

function getInitialToken() {
  const token = document.querySelector<HTMLMetaElement>(
    'meta[name="csrf-token"]',
  )?.content
  return token && token !== "__CSRF_TOKEN__" ? token : ""
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function parsePackageDate(value: string) {
  const match = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(value.trim())
  if (!match) return null
  const [, dayText, monthText, yearText] = match
  const day = Number(dayText)
  const month = Number(monthText)
  const year = Number(yearText)
  const timestamp = Date.UTC(year, month - 1, day)
  const parsed = new Date(timestamp)
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null
  }
  return timestamp
}

function StatusBadge({ item }: { item: PackageItem }) {
  const variant =
    item.status === "outdated"
      ? "warning"
      : item.status === "up_to_date"
        ? "success"
        : "secondary"
  return <Badge variant={variant}>{item.status_label}</Badge>
}

function SortableHeader({
  column,
  label,
  sort,
  onSort,
  alignRight = false,
}: {
  column: SortColumn
  label: string
  sort: SortState | null
  onSort: (column: SortColumn) => void
  alignRight?: boolean
}) {
  const active = sort?.column === column
  const Icon = active
    ? sort.direction === "asc"
      ? ArrowUp
      : ArrowDown
    : null

  return (
    <th
      aria-sort={
        active
          ? sort.direction === "asc"
            ? "ascending"
            : "descending"
          : "none"
      }
      className={cn("px-3 py-2.5 font-medium", alignRight && "text-right")}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn(
          "-mx-2 h-7 text-xs text-muted-foreground hover:text-foreground",
          alignRight && "flex-row-reverse",
        )}
        onClick={() => onSort(column)}
      >
        {label}
        {Icon ? <Icon className="size-3.5" /> : <span className="size-3.5" aria-hidden />}
      </Button>
    </th>
  )
}

function comparePackageItems(
  left: PackageItem,
  right: PackageItem,
  column: SortColumn,
  locale: Intl.Collator,
) {
  switch (column) {
    case "package":
      return (
        locale.compare(left.title || left.filename, right.title || right.filename) ||
        locale.compare(left.filename, right.filename)
      )
    case "category":
      return locale.compare(left.category, right.category)
    case "status": {
      const order: Record<PackageStatus, number> = {
        outdated: 0,
        not_installed: 1,
        up_to_date: 2,
      }
      return order[left.status] - order[right.status]
    }
    case "date": {
      const leftDate = parsePackageDate(left.date)
      const rightDate = parsePackageDate(right.date)
      if (leftDate === null) return rightDate === null ? 0 : 1
      if (rightDate === null) return -1
      return leftDate - rightDate
    }
    case "size":
      return left.size_bytes - right.size_bytes
  }
}

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof TrainFront
  label: string
  value: string | number
  tone?: "warning" | "success" | "muted"
}) {
  return (
    <Card size="sm">
      <CardContent className="flex items-center gap-3">
        <div
          className={cn(
            "flex size-10 items-center justify-center rounded-xl bg-muted",
            tone === "warning" && "bg-amber-500/10 text-amber-700",
            tone === "success" && "bg-emerald-500/10 text-emerald-700",
            tone === "muted" && "text-muted-foreground",
          )}
        >
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="text-xl font-semibold tracking-tight">{value}</div>
          <div className="truncate text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
}

export default function App() {
  const [appState, setAppState] = useState<AppState | null>(null)
  const [selectedNames, setSelectedNames] = useState<string[]>([])
  const [path, setPath] = useState("")
  const [createBackup, setCreateBackup] = useState(true)
  const [autoKill, setAutoKill] = useState(true)
  const [launchAfter, setLaunchAfter] = useState(false)
  const [settingsDirty, setSettingsDirty] = useState(false)
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState("all")
  const [statusFilter, setStatusFilter] = useState("all")
  const [sort, setSort] = useState<SortState | null>(null)
  const [presetValue, setPresetValue] = useState("")
  const [notice, setNotice] = useState("")
  const [noticeError, setNoticeError] = useState(false)
  const [working, setWorking] = useState(false)
  const selectionTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const csrfRef = useRef(getInitialToken())
  const selectedRef = useRef<string[]>([])

  const request = useCallback(
    async (url: string, payload?: Record<string, unknown>) => {
      const headers: Record<string, string> = {}
      const options: RequestInit = { cache: "no-store" }
      if (payload !== undefined) {
        headers["Content-Type"] = "application/json"
        headers["X-IDO-CSRF-Token"] = csrfRef.current
        options.method = "POST"
        options.body = JSON.stringify(payload)
      }
      options.headers = headers

      const response = await fetch(url, options)
      const result = (await response.json()) as ApiResponse
      if (!response.ok) {
        throw new Error(result.error ?? `Požadavek selhal (${response.status}).`)
      }
      if (result.csrf_token) {
        csrfRef.current = result.csrf_token
      }
      if (result.state) setAppState(result.state)
      else if ("refresh_state" in result) setAppState(result as AppState)
      return result
    },
    [],
  )

  const reportError = useCallback((error: unknown) => {
    setNotice(error instanceof Error ? error.message : "Nastala neznámá chyba.")
    setNoticeError(true)
    setWorking(false)
  }, [])

  const runAction = useCallback(
    async (action: string, payload: Record<string, unknown> = {}) => {
      setWorking(true)
      try {
        await request(`/api/${action}`, payload)
      } catch (error) {
        reportError(error)
      } finally {
        setWorking(false)
      }
    },
    [reportError, request],
  )

  const refreshState = useCallback(async () => {
    try {
      await request("/api/state")
    } catch (error) {
      reportError(error)
    }
  }, [reportError, request])

  useEffect(() => {
    let mounted = true
    const initialize = async () => {
      try {
        if (!csrfRef.current) {
          const result = await request("/api/csrf")
          if (!mounted || !result.csrf_token) return
        }
        await refreshState()
      } catch (error) {
        if (mounted) reportError(error)
      }
    }
    void initialize()
    const interval = window.setInterval(() => void refreshState(), 1200)
    return () => {
      mounted = false
      window.clearInterval(interval)
      if (selectionTimer.current) window.clearTimeout(selectionTimer.current)
    }
  }, [refreshState, reportError, request])

  useEffect(() => {
    if (!appState) return
    selectedRef.current = appState.items
      .filter((item) => item.selected)
      .map((item) => item.filename)
    setSelectedNames(selectedRef.current)
    if (!settingsDirty) {
      setPath(appState.path)
      setCreateBackup(appState.create_backup)
      setAutoKill(appState.auto_kill_idos)
      setLaunchAfter(appState.launch_after_update)
    }
  }, [appState, settingsDirty])

  const counts = useMemo(() => {
    const totals = { outdated: 0, up_to_date: 0, not_installed: 0 }
    for (const item of appState?.items ?? []) totals[item.status] += 1
    return totals
  }, [appState])

  const categories = useMemo(
    () =>
      Array.from(new Set(appState?.items.map((item) => item.category) ?? [])).sort(
        (left, right) => left.localeCompare(right, "cs"),
      ),
    [appState],
  )

  const filteredItems = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("cs")
    const filtered = (appState?.items ?? []).filter((item) => {
      const searchable =
        `${item.filename} ${item.title} ${item.description} ${item.category}`.toLocaleLowerCase(
          "cs",
        )
      return (
        (!query || searchable.includes(query)) &&
        (category === "all" || item.category === category) &&
        (statusFilter === "all" || item.status === statusFilter)
      )
    })
    if (!sort) return filtered

    const collator = new Intl.Collator("cs", {
      numeric: true,
      sensitivity: "base",
    })
    const originalOrder = new Map(
      (appState?.items ?? []).map((item, index) => [item.filename, index]),
    )
    const direction = sort.direction === "asc" ? 1 : -1
    return filtered.toSorted((left, right) => {
      const comparison = comparePackageItems(left, right, sort.column, collator)
      if (sort.column === "date") {
        const leftDate = parsePackageDate(left.date)
        const rightDate = parsePackageDate(right.date)
        if (leftDate === null && rightDate !== null) return 1
        if (leftDate !== null && rightDate === null) return -1
        if (leftDate === null && rightDate === null) {
          return originalOrder.get(left.filename)! - originalOrder.get(right.filename)!
        }
      }
      return (
        comparison * direction ||
        originalOrder.get(left.filename)! - originalOrder.get(right.filename)!
      )
    })
  }, [appState, category, search, sort, statusFilter])

  const changeSort = (column: SortColumn) => {
    setSort((current) =>
      current?.column === column
        ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
        : { column, direction: "asc" },
    )
  }

  const isLoading = appState?.refresh_state === "loading"
  const isUpdating = appState?.update_state === "running"
  const isReady = appState?.refresh_state === "ready"
  const selectedCount = selectedNames.length
  const progress = appState?.progress
  const selectedBytes = (appState?.items ?? [])
    .filter((item) => selectedNames.includes(item.filename))
    .reduce((total, item) => total + item.size_bytes, 0)

  const saveSettings = async () => {
    setWorking(true)
    try {
      await request("/api/settings", {
        path,
        create_backup: createBackup,
        auto_kill_idos: autoKill,
        launch_after_update: launchAfter,
      })
      setSettingsDirty(false)
      setNotice("Nastavení bylo uloženo.")
      setNoticeError(false)
    } catch (error) {
      reportError(error)
    } finally {
      setWorking(false)
    }
  }

  const togglePackage = (filename: string, checked: boolean) => {
    const next = checked
      ? Array.from(new Set([...selectedRef.current, filename]))
      : selectedRef.current.filter((name) => name !== filename)
    selectedRef.current = next
    setSelectedNames(next)
    if (selectionTimer.current) window.clearTimeout(selectionTimer.current)
    selectionTimer.current = window.setTimeout(() => {
      void request("/api/selection", { filenames: next }).catch(reportError)
    }, 100)
  }

  const invokeSelectionAction = async (action: RequestAction) => {
    setWorking(true)
    try {
      await request("/api/select-action", { action })
      setNotice("Výběr balíčků byl aktualizován.")
      setNoticeError(false)
    } catch (error) {
      reportError(error)
    } finally {
      setWorking(false)
    }
  }

  const beginUpdate = async () => {
    if (!selectedCount) {
      setNotice("Vyberte alespoň jeden balíček k aktualizaci.")
      setNoticeError(true)
      return
    }
    setWorking(true)
    try {
      await request("/api/settings", {
        path,
        create_backup: createBackup,
        auto_kill_idos: autoKill,
        launch_after_update: launchAfter,
      })
      setSettingsDirty(false)
      await request("/api/selection", { filenames: selectedRef.current })
      await request("/api/update", {})
      setNotice("Aktualizace byla spuštěna.")
      setNoticeError(false)
    } catch (error) {
      reportError(error)
    } finally {
      setWorking(false)
    }
  }

  const handleRefresh = async () => {
    await runAction("refresh", {})
  }

  const handleAutodetect = async () => {
    await runAction("autodetect", {})
    setSettingsDirty(false)
  }

  const appTitle =
    appState?.refresh_state === "error"
      ? "Nabídku se nepodařilo načíst"
      : appState?.refresh_state === "ready"
        ? "Spravujte aktualizace IDOS"
        : "Připravuji aktualizace"

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <TrainFront className="size-5" />
            </div>
            <div>
              <div className="font-semibold leading-tight">IDOS Updater</div>
              <div className="text-xs text-muted-foreground">Lokální webová aplikace</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={appState?.idos_running ? "warning" : "outline"}>
              <span
                className={cn(
                  "mr-1.5 size-1.5 rounded-full",
                  appState?.idos_running ? "bg-amber-600" : "bg-emerald-600",
                )}
              />
              {appState?.idos_running ? "IDOS běží" : "IDOS neběží"}
            </Badge>
            <Button
              variant="outline"
              size="icon"
              title="Obnovit stav"
              onClick={() => void refreshState()}
              disabled={working || isLoading}
            >
              <RefreshCw className={cn("size-4", isLoading && "animate-spin")} />
              <span className="sr-only">Obnovit stav</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-7 sm:px-6 lg:px-8">
        <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-sm font-medium text-primary">
              <Sparkles className="size-4" />
              CHAPS · balíčky a jízdní řády
            </div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{appTitle}</h1>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Vyhledejte dostupné balíčky, zkontrolujte jejich stav a aktualizujte instalaci z
              jednoho místa.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void runAction("launch", {})}
            disabled={working || isUpdating}
          >
            <Play className="size-4" />
            Spustit IDOS
          </Button>
        </section>

        {notice && (
          <div
            role={noticeError ? "alert" : "status"}
            className={cn(
              "flex items-center gap-2 rounded-xl border px-4 py-3 text-sm",
              noticeError
                ? "border-destructive/30 bg-destructive/5 text-destructive"
                : "border-primary/20 bg-primary/5 text-foreground",
            )}
          >
            {noticeError ? <AlertCircle className="size-4 shrink-0" /> : <Check className="size-4 shrink-0" />}
            <span>{notice}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              className="ml-auto"
              onClick={() => setNotice("")}
              aria-label="Zavřít zprávu"
            >
              <X className="size-3.5" />
            </Button>
          </div>
        )}

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard icon={ArrowDownToLine} label="Vybráno ke stažení" value={selectedCount} />
          <StatCard
            icon={Clock3}
            label="Vyžaduje aktualizaci"
            value={counts.outdated}
            tone="warning"
          />
          <StatCard
            icon={CheckCheck}
            label="Aktuální"
            value={counts.up_to_date}
            tone="success"
          />
          <StatCard
            icon={CircleHelp}
            label="Nenainstalováno"
            value={counts.not_installed}
            tone="muted"
          />
        </section>

        <section className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.8fr)]">
          <Card className="min-w-0">
            <CardHeader className="flex-row items-start justify-between gap-4 border-b pb-4">
              <div className="space-y-1">
                <CardTitle className="text-base">Dostupné balíčky</CardTitle>
                <p className="text-sm text-muted-foreground">
                  {appState?.items.length ?? 0} balíčků z nabídky CHAPS
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleRefresh()}
                disabled={working || isLoading || isUpdating}
              >
                <RefreshCw className={cn("size-4", isLoading && "animate-spin")} />
                Obnovit
              </Button>
            </CardHeader>
            <CardContent className="min-w-0 space-y-4 pt-4">
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_200px_190px]">
                <div className="relative">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="pl-9"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Hledat podle názvu, souboru…"
                    aria-label="Hledat balíčky"
                  />
                </div>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger aria-label="Filtrovat podle kategorie">
                    <SelectValue placeholder="Všechny kategorie" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Všechny kategorie</SelectItem>
                    {categories.map((value) => (
                      <SelectItem key={value} value={value}>
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger aria-label="Filtrovat podle stavu">
                    <SelectValue placeholder="Všechny stavy" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Všechny stavy</SelectItem>
                    <SelectItem value="outdated">Vyžaduje aktualizaci</SelectItem>
                    <SelectItem value="up_to_date">Aktuální</SelectItem>
                    <SelectItem value="not_installed">Nenainstalováno</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={presetValue}
                  onValueChange={(value) => {
                    setPresetValue(value)
                    void invokeSelectionAction(value as RequestAction).finally(() =>
                      setPresetValue(""),
                    )
                  }}
                >
                  <SelectTrigger className="w-[190px]" disabled={working || !isReady || isUpdating}>
                    <Settings2 className="size-4 text-muted-foreground" />
                    <SelectValue placeholder="Rychlý výběr" />
                  </SelectTrigger>
                  <SelectContent>
                    {actionLabels.map(({ action, label }) => (
                      <SelectItem key={action} value={action}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void invokeSelectionAction("all")}
                  disabled={working || !isReady || isUpdating}
                >
                  Vybrat vše
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void invokeSelectionAction("clear")}
                  disabled={working || !isReady || isUpdating}
                >
                  Zrušit výběr
                </Button>
                <span className="ml-auto text-xs text-muted-foreground">
                  Odhad velikosti: {formatBytes(selectedBytes)}
                </span>
              </div>

              <div className="overflow-hidden rounded-xl border">
                <div className="min-w-0 overflow-x-auto">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead className="bg-muted/90 text-xs text-muted-foreground">
                      <tr>
                        <th className="w-10 px-3 py-2.5 font-medium">
                          <span className="sr-only">Výběr</span>
                        </th>
                        <SortableHeader column="package" label="Balíček" sort={sort} onSort={changeSort} />
                        <SortableHeader column="category" label="Kategorie" sort={sort} onSort={changeSort} />
                        <SortableHeader column="status" label="Stav" sort={sort} onSort={changeSort} />
                        <SortableHeader column="date" label="Aktualizace" sort={sort} onSort={changeSort} />
                        <SortableHeader column="size" label="Velikost" sort={sort} onSort={changeSort} alignRight />
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {filteredItems.map((item) => (
                        <tr
                          key={item.filename}
                          className="transition-colors hover:bg-muted/40"
                        >
                          <td className="px-3 py-3">
                            <Checkbox
                              checked={selectedNames.includes(item.filename)}
                              disabled={isUpdating}
                              onCheckedChange={(checked) =>
                                togglePackage(item.filename, checked === true)
                              }
                              aria-label={`Vybrat ${item.filename}`}
                            />
                          </td>
                          <td className="max-w-[280px] px-3 py-3">
                            <div className="truncate font-medium" title={item.title}>
                              {item.title || item.filename}
                            </div>
                            <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                              <span className="font-mono">{item.filename}</span>
                            </div>
                          </td>
                          <td className="max-w-[220px] truncate px-3 py-3 text-xs text-muted-foreground" title={item.category}>
                            {item.category || "—"}
                          </td>
                          <td className="px-3 py-3">
                            <StatusBadge item={item} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-3 text-xs text-muted-foreground">
                            {item.date || "—"}
                          </td>
                          <td className="whitespace-nowrap px-3 py-3 text-right text-xs text-muted-foreground">
                            {item.size || "—"}
                          </td>
                        </tr>
                      ))}
                      {!filteredItems.length && (
                        <tr>
                          <td
                            colSpan={6}
                            className="px-4 py-12 text-center text-sm text-muted-foreground"
                          >
                            {isLoading
                              ? "Načítám nabídku balíčků…"
                              : appState?.refresh_state === "error"
                                ? appState.refresh_error
                                : appState?.items.length
                                  ? "Filtru neodpovídají žádné balíčky."
                                  : "Zatím nejsou načtené žádné balíčky."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between border-t bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  <span>
                    Zobrazeno {filteredItems.length} z {appState?.items.length ?? 0}
                  </span>
                  <span>{selectedCount} vybráno</span>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card>
              <CardHeader className="border-b pb-4">
                <CardTitle className="flex items-center gap-2 text-base">
                  <FolderOpen className="size-4 text-muted-foreground" />
                  Cílová instalace
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  Nastavte složku, do které se balíčky nainstalují.
                </p>
              </CardHeader>
              <CardContent className="space-y-4 pt-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="idos-path">
                    Cesta k IDOS
                  </label>
                  <Input
                    id="idos-path"
                    value={path}
                    disabled={isUpdating}
                    onChange={(event) => {
                      setPath(event.target.value)
                      setSettingsDirty(true)
                    }}
                    placeholder="C:\\IDOS"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleAutodetect()}
                    disabled={working || isUpdating}
                  >
                    <Search className="size-4" />
                    Autodetekce
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void saveSettings()}
                    disabled={working || isUpdating || !settingsDirty}
                  >
                    Uložit nastavení
                  </Button>
                </div>
                <div className="space-y-3 border-t pt-4">
                  <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                    <Checkbox
                      checked={createBackup}
                      disabled={isUpdating}
                      onCheckedChange={(checked) => {
                        setCreateBackup(checked === true)
                        setSettingsDirty(true)
                      }}
                    />
                    <span>
                      Vytvořit zálohu
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        Před instalací uložit současná data.
                      </span>
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                    <Checkbox
                      checked={autoKill}
                      disabled={isUpdating}
                      onCheckedChange={(checked) => {
                        setAutoKill(checked === true)
                        setSettingsDirty(true)
                      }}
                    />
                    <span>
                      Ukončit běžící IDOS
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        Zavřít TT.exe před přepsáním souborů.
                      </span>
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                    <Checkbox
                      checked={launchAfter}
                      disabled={isUpdating}
                      onCheckedChange={(checked) => {
                        setLaunchAfter(checked === true)
                        setSettingsDirty(true)
                      }}
                    />
                    <span>Spustit IDOS po aktualizaci</span>
                  </label>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="border-b pb-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <HardDrive className="size-4 text-muted-foreground" />
                    Průběh aktualizace
                  </CardTitle>
                  <Badge
                    variant={
                      isUpdating
                        ? "default"
                        : appState?.update_state === "error"
                          ? "destructive"
                          : appState?.update_state === "done"
                            ? "success"
                            : "secondary"
                    }
                  >
                    {isUpdating
                      ? "Probíhá"
                      : appState?.update_state === "done"
                        ? "Dokončeno"
                        : appState?.update_state === "cancelled"
                          ? "Zrušeno"
                          : appState?.update_state === "error"
                            ? "Chyba"
                            : "Připraveno"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 pt-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span className="truncate pr-3">
                      {progress?.filename
                        ? `${progress.item_index}/${progress.item_count} · ${progress.filename}`
                        : appState?.update_summary || "Čeká na spuštění"}
                    </span>
                    <span className="shrink-0">
                      {Math.round((progress?.overall_ratio ?? 0) * 100)}%
                    </span>
                  </div>
                  <Progress value={(progress?.overall_ratio ?? 0) * 100} className="h-2" />
                  {progress?.filename && (
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>
                        {formatBytes(progress.downloaded)} / {formatBytes(progress.total)}
                      </span>
                      <span>{progress.speed}</span>
                    </div>
                  )}
                </div>
                {appState?.update_error && (
                  <p role="alert" className="text-sm text-destructive">
                    {appState.update_error}
                  </p>
                )}
                <div className="flex gap-2">
                  <Button
                    className="flex-1"
                    onClick={() => void beginUpdate()}
                    disabled={working || isUpdating || !isReady || !selectedCount}
                  >
                    {working || isUpdating ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <Play className="size-4" />
                    )}
                    Aktualizovat {selectedCount ? `(${selectedCount})` : ""}
                  </Button>
                  {isUpdating && (
                    <Button
                      variant="destructive"
                      size="icon"
                      title="Zrušit aktualizaci"
                      onClick={() => void runAction("cancel", {})}
                      disabled={working}
                    >
                      <X className="size-4" />
                      <span className="sr-only">Zrušit aktualizaci</span>
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <ShieldCheck className="size-4 text-emerald-600" />
                  Webový server je dostupný pouze na tomto počítači.
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-center justify-between pb-3">
                <CardTitle className="text-base">Protokol</CardTitle>
                <Badge variant="outline">{appState?.logs.length ?? 0}</Badge>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="max-h-48 space-y-1 overflow-auto rounded-lg bg-muted/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  {(appState?.logs ?? []).slice(-60).map((line, index) => (
                    <div key={`${index}-${line}`} className="break-words">
                      {line}
                    </div>
                  ))}
                  {!appState?.logs.length && <span>Protokol je zatím prázdný.</span>}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        {working && (
          <div className="sr-only" aria-live="polite">
            Probíhá požadavek…
          </div>
        )}
      </main>
      <footer className="border-t bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-4 text-xs text-muted-foreground sm:px-6 lg:px-8">
          <span>IDOS Updater · lokální aplikace</span>
          <span className="flex items-center gap-1.5">
            <ChevronDown className="size-3.5" />
            Data balíčků poskytuje CHAPS
          </span>
        </div>
      </footer>
    </div>
  )
}
