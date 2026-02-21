import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { format as formatDateFns } from "date-fns";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  Filter,
  X,
  Download,
  Loader2,
  AlertCircle,
  Calendar as CalendarIcon,
} from "lucide-react";

// Debounce hook
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

// Parse filters from URL query string
function parseFiltersFromURL(searchParams, columns) {
  const filters = {};
  columns.forEach((col) => {
    if (col.filterable) {
      const value = searchParams.get(`f_${col.key}`);
      if (value) filters[col.key] = value;
    }
  });
  return filters;
}

// Build filter string for API
function buildFilterString(filters, columns) {
  const parts = [];
  Object.entries(filters).forEach(([key, value]) => {
    if (!value) return;
    const col = columns.find((c) => c.key === key);
    if (!col) return;

    const filterType = col.filterType || "contains";
    if (filterType === "contains" || filterType === "equals") {
      parts.push(`${key}.${filterType}=${encodeURIComponent(value)}`);
    } else if (filterType === "in") {
      parts.push(`${key}.in=${encodeURIComponent(value)}`);
    } else if (filterType === "bool") {
      parts.push(`${key}.bool=${value}`);
    } else if (filterType === "dateRange") {
      // value format: "from|to"
      const [from, to] = value.split("|");
      if (from) parts.push(`${key}.from=${from}`);
      if (to) parts.push(`${key}.to=${to}`);
    } else if (filterType === "numberRange") {
      // value format: "min|max"
      const [min, max] = value.split("|");
      if (min) parts.push(`${key}.min=${min}`);
      if (max) parts.push(`${key}.max=${max}`);
    }
  });
  return parts.join(",");
}

// Export to CSV
function exportToCSV(data, columns, filename = "export.csv") {
  const headers = columns.map((c) => c.label).join(",");
  const rows = data.map((row) =>
    columns
      .map((col) => {
        const value = row[col.key];
        if (value === null || value === undefined) return "";
        const str = String(value).replace(/"/g, '""');
        return str.includes(",") || str.includes('"') || str.includes("\n")
          ? `"${str}"`
          : str;
      })
      .join(",")
  );
  const csv = [headers, ...rows].join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
}

// Column Filter Component
function ColumnFilter({ column, value, onChange }) {
  const { t } = useTranslation();
  const filterType = column.filterType || "contains";

  if (filterType === "contains" || filterType === "equals") {
    return (
      <Input
        placeholder={t("common.search")}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 text-xs"
      />
    );
  }

  if (filterType === "in" && column.options) {
    const selected = value ? value.split("|") : [];
    return (
      <div className="space-y-1 max-h-40 overflow-y-auto">
        {column.options.map((opt) => (
          <label key={opt.value} className="flex items-center gap-2 text-xs">
            <Checkbox
              checked={selected.includes(opt.value)}
              onCheckedChange={(checked) => {
                const newSelected = checked
                  ? [...selected, opt.value]
                  : selected.filter((v) => v !== opt.value);
                onChange(newSelected.join("|") || null);
              }}
            />
            {opt.label}
          </label>
        ))}
      </div>
    );
  }

  if (filterType === "bool") {
    return (
      <Select value={value || ""} onValueChange={(v) => onChange(v || null)}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder={t("common.all")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="">{t("common.all")}</SelectItem>
          <SelectItem value="true">{t("common.yes")}</SelectItem>
          <SelectItem value="false">{t("common.no")}</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  if (filterType === "dateRange") {
    const [from, to] = (value || "|").split("|");
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">{t("common.from")}:</span>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-8 text-xs flex-1">
                {from || <CalendarIcon className="w-3 h-3" />}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0">
              <Calendar
                mode="single"
                selected={from ? new Date(from) : undefined}
                onSelect={(date) => {
                  const newFrom = date ? formatDateFns(date, "yyyy-MM-dd") : "";
                  onChange(`${newFrom}|${to}`);
                }}
              />
            </PopoverContent>
          </Popover>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">{t("common.to")}:</span>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-8 text-xs flex-1">
                {to || <CalendarIcon className="w-3 h-3" />}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0">
              <Calendar
                mode="single"
                selected={to ? new Date(to) : undefined}
                onSelect={(date) => {
                  const newTo = date ? formatDateFns(date, "yyyy-MM-dd") : "";
                  onChange(`${from}|${newTo}`);
                }}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>
    );
  }

  if (filterType === "numberRange") {
    const [min, max] = (value || "|").split("|");
    return (
      <div className="flex gap-2">
        <Input
          type="number"
          placeholder="Min"
          value={min || ""}
          onChange={(e) => onChange(`${e.target.value}|${max}`)}
          className="h-8 text-xs w-20"
        />
        <Input
          type="number"
          placeholder="Max"
          value={max || ""}
          onChange={(e) => onChange(`${min}|${e.target.value}`)}
          className="h-8 text-xs w-20"
        />
      </div>
    );
  }

  return null;
}

/**
 * DataTable Component
 * 
 * Props:
 * - columns: Array of column definitions
 *   - key: string (field name)
 *   - label: string (display name)
 *   - sortable: boolean
 *   - filterable: boolean
 *   - filterType: "contains" | "equals" | "in" | "bool" | "dateRange" | "numberRange"
 *   - options: Array<{value, label}> (for filterType="in")
 *   - render: (value, row) => ReactNode (custom render)
 *   - width: string (e.g., "150px")
 * - fetchData: async (params) => { items, total, page, page_size }
 *   - params: { page, page_size, sort_by, sort_dir, search, filters }
 * - onRowClick: (row) => void
 * - actions: (row) => ReactNode (render actions column)
 * - exportFilename: string
 * - searchPlaceholder: string
 * - emptyMessage: string
 * - pageSize: number (default 20)
 */
export default function DataTable({
  columns,
  fetchData,
  onRowClick,
  actions,
  exportFilename = "export.csv",
  searchPlaceholder,
  emptyMessage,
  pageSize: defaultPageSize = 20,
  refreshKey,
}) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  // State from URL
  const page = parseInt(searchParams.get("page") || "1", 10);
  const pageSize = parseInt(searchParams.get("pageSize") || String(defaultPageSize), 10);
  const sortBy = searchParams.get("sortBy") || "";
  const sortDir = searchParams.get("sortDir") || "asc";
  const searchQuery = searchParams.get("search") || "";

  // Local state
  const [localSearch, setLocalSearch] = useState(searchQuery);
  const [filters, setFilters] = useState(() => parseFiltersFromURL(searchParams, columns));
  const [showFilters, setShowFilters] = useState(false);
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Debounced search
  const debouncedSearch = useDebounce(localSearch, 400);

  // Update URL when search changes
  useEffect(() => {
    if (debouncedSearch !== searchQuery) {
      updateParams({ search: debouncedSearch, page: 1 });
    }
  }, [debouncedSearch]);

  // Update URL params helper
  const updateParams = useCallback(
    (updates) => {
      const newParams = new URLSearchParams(searchParams);
      Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === undefined || value === "" || value === 1 && key === "page") {
          newParams.delete(key);
        } else {
          newParams.set(key, String(value));
        }
      });
      setSearchParams(newParams, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  // Update filter in URL
  const updateFilter = useCallback(
    (key, value) => {
      const newFilters = { ...filters };
      if (value) {
        newFilters[key] = value;
      } else {
        delete newFilters[key];
      }
      setFilters(newFilters);

      // Update URL
      const newParams = new URLSearchParams(searchParams);
      if (value) {
        newParams.set(`f_${key}`, value);
      } else {
        newParams.delete(`f_${key}`);
      }
      newParams.set("page", "1"); // Reset to page 1 on filter change
      setSearchParams(newParams, { replace: true });
    },
    [filters, searchParams, setSearchParams]
  );

  // Clear all filters
  const clearFilters = useCallback(() => {
    setFilters({});
    setLocalSearch("");
    const newParams = new URLSearchParams();
    if (sortBy) newParams.set("sortBy", sortBy);
    if (sortDir !== "asc") newParams.set("sortDir", sortDir);
    setSearchParams(newParams, { replace: true });
  }, [sortBy, sortDir, setSearchParams]);

  // Fetch data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filterString = buildFilterString(filters, columns);
      const result = await fetchData({
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_dir: sortDir,
        search: debouncedSearch,
        filters: filterString,
      });
      setData(result.items || []);
      setTotal(result.total || 0);
    } catch (err) {
      console.error("DataTable fetch error:", err);
      setError(err.message || t("common.error"));
      setData([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, sortBy, sortDir, debouncedSearch, filters, columns, fetchData, t]);

  useEffect(() => {
    loadData();
  }, [loadData, refreshKey]);

  // Pagination
  const totalPages = Math.ceil(total / pageSize);

  const handleSort = (key) => {
    if (!columns.find((c) => c.key === key)?.sortable) return;
    const newDir = sortBy === key && sortDir === "asc" ? "desc" : "asc";
    updateParams({ sortBy: key, sortDir: newDir });
  };

  // Export current filtered data
  const handleExport = () => {
    const exportCols = columns.filter((c) => c.key !== "actions");
    exportToCSV(data, exportCols, exportFilename);
  };

  // Count active filters
  const activeFilterCount = Object.keys(filters).length + (debouncedSearch ? 1 : 0);

  // Render sort icon
  const renderSortIcon = (key) => {
    if (sortBy !== key) return <ArrowUpDown className="w-3 h-3 opacity-40" />;
    return sortDir === "asc" ? (
      <ArrowUp className="w-3 h-3 text-primary" />
    ) : (
      <ArrowDown className="w-3 h-3 text-primary" />
    );
  };

  return (
    <div className="space-y-4" data-testid="data-table">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder={searchPlaceholder || t("common.search")}
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="pl-9 h-9"
            data-testid="data-table-search"
          />
          {localSearch && (
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6"
              onClick={() => setLocalSearch("")}
            >
              <X className="w-3 h-3" />
            </Button>
          )}
        </div>

        {/* Filter toggle */}
        <Button
          variant={showFilters ? "secondary" : "outline"}
          size="sm"
          onClick={() => setShowFilters(!showFilters)}
          data-testid="data-table-filter-toggle"
        >
          <Filter className="w-4 h-4 mr-1" />
          {t("common.filter")}
          {activeFilterCount > 0 && (
            <Badge variant="secondary" className="ml-1 h-5 px-1.5">
              {activeFilterCount}
            </Badge>
          )}
        </Button>

        {/* Clear filters */}
        {activeFilterCount > 0 && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="w-4 h-4 mr-1" />
            {t("common.reset")}
          </Button>
        )}

        {/* Export */}
        <Button variant="outline" size="sm" onClick={handleExport} data-testid="data-table-export">
          <Download className="w-4 h-4 mr-1" />
          CSV
        </Button>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div
          className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 p-4 bg-muted/50 rounded-lg border"
          data-testid="data-table-filters"
        >
          {columns
            .filter((col) => col.filterable)
            .map((col) => (
              <div key={col.key} className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  {col.label}
                </label>
                <ColumnFilter
                  column={col}
                  value={filters[col.key]}
                  onChange={(value) => updateFilter(col.key, value)}
                />
              </div>
            ))}
        </div>
      )}

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                {columns.map((col) => (
                  <TableHead
                    key={col.key}
                    style={{ width: col.width }}
                    className={col.sortable ? "cursor-pointer select-none" : ""}
                    onClick={() => col.sortable && handleSort(col.key)}
                  >
                    <div className="flex items-center gap-1">
                      {col.label}
                      {col.sortable && renderSortIcon(col.key)}
                    </div>
                  </TableHead>
                ))}
                {actions && <TableHead className="w-[100px]">{t("common.actions")}</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={columns.length + (actions ? 1 : 0)} className="h-32">
                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                      <Loader2 className="w-5 h-5 animate-spin" />
                      {t("common.loading")}
                    </div>
                  </TableCell>
                </TableRow>
              ) : error ? (
                <TableRow>
                  <TableCell colSpan={columns.length + (actions ? 1 : 0)} className="h-32">
                    <div className="flex items-center justify-center gap-2 text-destructive">
                      <AlertCircle className="w-5 h-5" />
                      {error}
                    </div>
                  </TableCell>
                </TableRow>
              ) : data.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns.length + (actions ? 1 : 0)} className="h-32">
                    <div className="flex items-center justify-center text-muted-foreground">
                      {emptyMessage || t("common.noData")}
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                data.map((row, idx) => (
                  <TableRow
                    key={row.id || idx}
                    className={onRowClick ? "cursor-pointer hover:bg-muted/50" : ""}
                    onClick={() => onRowClick?.(row)}
                    data-testid={`data-table-row-${idx}`}
                  >
                    {columns.map((col) => (
                      <TableCell key={col.key}>
                        {col.render ? col.render(row[col.key], row) : row[col.key]}
                      </TableCell>
                    ))}
                    {actions && (
                      <TableCell onClick={(e) => e.stopPropagation()}>{actions(row)}</TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 0 && (
        <div className="flex items-center justify-between" data-testid="data-table-pagination">
          <div className="text-sm text-muted-foreground">
            {t("common.showing")} {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} {t("common.of")} {total}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page <= 1}
              onClick={() => updateParams({ page: 1 })}
            >
              <ChevronsLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page <= 1}
              onClick={() => updateParams({ page: page - 1 })}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="px-3 text-sm">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page >= totalPages}
              onClick={() => updateParams({ page: page + 1 })}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page >= totalPages}
              onClick={() => updateParams({ page: totalPages })}
            >
              <ChevronsRight className="w-4 h-4" />
            </Button>
          </div>
          <Select
            value={String(pageSize)}
            onValueChange={(v) => updateParams({ pageSize: parseInt(v, 10), page: 1 })}
          >
            <SelectTrigger className="w-[100px] h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[10, 20, 50, 100].map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {size} / {t("common.page")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  );
}
