import * as React from "react"
import { format } from "date-fns"
import { Calendar as CalendarIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

/**
 * DatePicker component using shadcn Calendar with proper dark mode support.
 * 
 * Props:
 * - value: string (ISO date format YYYY-MM-DD) or Date object
 * - onChange: (date: string) => void - returns ISO date string
 * - placeholder: string
 * - disabled: boolean
 * - className: string
 */
export function DatePicker({ 
  value, 
  onChange, 
  placeholder = "Pick a date",
  disabled = false,
  className,
  ...props 
}) {
  // Convert string to Date for calendar
  const dateValue = React.useMemo(() => {
    if (!value) return undefined;
    if (value instanceof Date) return value;
    // Parse ISO date string
    const parsed = new Date(value + "T00:00:00");
    return isNaN(parsed.getTime()) ? undefined : parsed;
  }, [value]);

  const handleSelect = (date) => {
    if (date) {
      // Convert to ISO string (YYYY-MM-DD)
      const isoDate = format(date, "yyyy-MM-dd");
      onChange(isoDate);
    } else {
      onChange("");
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className={cn(
            "w-full justify-start text-left font-normal bg-background border-input",
            !dateValue && "text-muted-foreground",
            className
          )}
          data-testid={props["data-testid"]}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {dateValue ? format(dateValue, "dd.MM.yyyy") : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent 
        className="w-auto p-0 bg-popover border-border shadow-lg z-[100]" 
        align="start"
        sideOffset={4}
      >
        <Calendar
          mode="single"
          selected={dateValue}
          onSelect={handleSelect}
          initialFocus
          className="rounded-md"
        />
      </PopoverContent>
    </Popover>
  );
}
