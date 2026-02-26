/**
 * ActivityTypeSelect - Dropdown for activity type with optional subtype input
 * Used in offer lines to categorize activities for budget tracking.
 */
import { useState } from "react";
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
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Tags, ChevronDown } from "lucide-react";

const ACTIVITY_TYPES = [
  "Общо",
  "Земни",
  "Кофраж",
  "Арматура",
  "Бетон",
  "Зидария",
  "Покрив",
  "Изолации",
  "Фасада",
  "Инсталации",
  "Довършителни",
  "Други",
];

export default function ActivityTypeSelect({ 
  value = "Общо", 
  subtype = "", 
  onChange,
  compact = false 
}) {
  const [open, setOpen] = useState(false);
  const [localType, setLocalType] = useState(value);
  const [localSubtype, setLocalSubtype] = useState(subtype);
  
  const handleSave = () => {
    onChange?.(localType, localSubtype);
    setOpen(false);
  };
  
  const displayText = subtype ? `${value} / ${subtype}` : value;
  
  if (compact) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button 
            variant="ghost" 
            size="sm" 
            className="h-7 px-2 text-xs font-normal text-muted-foreground hover:text-foreground"
            data-testid="activity-type-trigger"
          >
            <Tags className="w-3 h-3 mr-1" />
            {displayText}
            <ChevronDown className="w-3 h-3 ml-1" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-64 p-3" align="start">
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Тип</Label>
              <Select value={localType} onValueChange={setLocalType}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACTIVITY_TYPES.map(t => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Подтип (optional)</Label>
              <Input
                value={localSubtype}
                onChange={(e) => setLocalSubtype(e.target.value)}
                placeholder="напр. Изкоп"
                className="h-8 text-sm"
              />
            </div>
            <Button size="sm" className="w-full" onClick={handleSave}>
              Приложи
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    );
  }
  
  return (
    <div className="flex items-center gap-2">
      <Select value={localType} onValueChange={(v) => { setLocalType(v); onChange?.(v, localSubtype); }}>
        <SelectTrigger className="w-[140px]" data-testid="activity-type-select">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ACTIVITY_TYPES.map(t => (
            <SelectItem key={t} value={t}>{t}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        value={localSubtype}
        onChange={(e) => { setLocalSubtype(e.target.value); onChange?.(localType, e.target.value); }}
        placeholder="Подтип"
        className="w-[120px]"
        data-testid="activity-subtype-input"
      />
    </div>
  );
}

// Export types for external use
export { ACTIVITY_TYPES };
